from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Sum
from django.db.models.functions import Coalesce
from django.utils.translation import gettext_lazy as _


# -------------------------
# Helpers
# -------------------------

def d0() -> Decimal:
    return Decimal("0")


def quantize_money(v: Decimal) -> Decimal:
    # 2 Nachkommastellen, kaufmännisch
    return v.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def sum_int(qs, field: str) -> int:
    """
    Sum für IntegerFields: None -> 0
    """
    return qs.aggregate(s=Coalesce(Sum(field), 0))["s"]


# -------------------------
# Choices
# -------------------------

class BuchungsTyp(models.TextChoices):
    ZUGANG = "ZUGANG", _("Zugang")
    ABGANG = "ABGANG", _("Abgang")
    RESERVIERT = "RESERVIERT", _("Reserviert")
    FREIGABE = "FREIGABE", _("Freigabe")
    KORREKTUR = "KORREKTUR", _("Korrektur")  # darf negativ sein


# -------------------------
# Abstrakte Buchung (DRY)
# -------------------------

class BuchungBase(models.Model):
    """
    Gemeinsame Buchungslogik: typ, auftragsnummer, bemerkung, datum
    Menge-Feld wird in den Kindklassen definiert (menge_stk / menge_lfm).
    """
    typ = models.CharField(max_length=20, choices=BuchungsTyp.choices)
    auftragsnummer = models.CharField(
        max_length=80,
        blank=True,
        help_text="Pflicht bei Reserviert/Freigabe (Freitext).",
    )
    bemerkung = models.CharField(max_length=200, blank=True)
    datum = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True
        ordering = ("-datum",)

    def clean(self):
        super().clean()
        if self.typ in (BuchungsTyp.RESERVIERT, BuchungsTyp.FREIGABE) and not self.auftragsnummer.strip():
            raise ValidationError({"auftragsnummer": "Bei Reserviert/Freigabe ist die Auftragsnummer Pflicht."})

    @staticmethod
    def validate_menge_by_typ(typ: str, menge: int, field_name: str):
        # Korrektur darf negativ, alle anderen nicht
        if typ != BuchungsTyp.KORREKTUR and menge < 0:
            raise ValidationError({field_name: "Nur Korrektur darf negativ sein."})
        # Reserviert/Freigabe/Zugang/Abgang sollten nicht 0 sein (optional, aber sinnvoll)
        if typ != BuchungsTyp.KORREKTUR and menge == 0:
            raise ValidationError({field_name: "Menge darf nicht 0 sein (außer bei Korrektur, wenn du bewusst 0 willst)."})

    def __str__(self):
        return f"{self.typ} | {self.datum:%Y-%m-%d %H:%M}"


# -------------------------
# 1) Plattenlager (Stammplatten)
# -------------------------

class PlatteStamm(models.Model):
    """
    Stammplatte (Vollformat). Bestand wird in Stück geführt.
    Preis wird als EUR pro m² gepflegt, Plattenpreis wird berechnet.
    """

    code = models.CharField(max_length=80, unique=True, help_text="Eindeutiger Code, z.B. W1000 ST9 19")

    LAENGE_MM_DEFAULT = 2800
    BREITE_MM_DEFAULT = 2070

    laenge_mm = models.PositiveIntegerField(default=LAENGE_MM_DEFAULT, editable=False)
    breite_mm = models.PositiveIntegerField(default=BREITE_MM_DEFAULT, editable=False)

    staerke_mm = models.DecimalField(max_digits=5, decimal_places=1)
    preis_eur_pro_qm = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        verbose_name = "Stammplatte"
        verbose_name_plural = "Stammplatten"
        ordering = ("code",)

    def __str__(self):
        return self.code

    @property
    def qm_vollformat(self) -> Decimal:
        return (Decimal(self.laenge_mm) / Decimal("1000")) * (Decimal(self.breite_mm) / Decimal("1000"))

    @property
    def plattenpreis(self) -> Decimal:
        return quantize_money(self.qm_vollformat * self.preis_eur_pro_qm)

    # Bestände über Buchungen
    def bestand_physisch_stk(self) -> int:
        qs = self.buchungen.all()
        zugang = sum_int(qs.filter(typ=BuchungsTyp.ZUGANG), "menge_stk")
        abgang = sum_int(qs.filter(typ=BuchungsTyp.ABGANG), "menge_stk")
        korrektur = sum_int(qs.filter(typ=BuchungsTyp.KORREKTUR), "menge_stk")
        return zugang - abgang + korrektur

    def bestand_reserviert_stk(self) -> int:
        qs = self.buchungen.all()
        reserviert = sum_int(qs.filter(typ=BuchungsTyp.RESERVIERT), "menge_stk")
        freigabe = sum_int(qs.filter(typ=BuchungsTyp.FREIGABE), "menge_stk")
        return reserviert - freigabe

    def bestand_verfuegbar_stk(self) -> int:
        return self.bestand_physisch_stk() - self.bestand_reserviert_stk()

    def lagerwert_physisch(self) -> Decimal:
        return quantize_money(Decimal(self.bestand_physisch_stk()) * self.plattenpreis)


class PlatteStammBuchung(BuchungBase):
    platte = models.ForeignKey(PlatteStamm, on_delete=models.CASCADE, related_name="buchungen")
    menge_stk = models.IntegerField(help_text="Ganze Stückzahl. Korrektur darf negativ sein.")

    class Meta(BuchungBase.Meta):
        verbose_name = "Buchung Stammplatte"
        verbose_name_plural = "Buchungen Stammplatten"

    def clean(self):
        super().clean()
        self.validate_menge_by_typ(self.typ, self.menge_stk, "menge_stk")

    def __str__(self):
        return f"{self.typ} {self.menge_stk} stk | {self.platte.code}"


# -------------------------
# 2) Restplattenlager
# -------------------------

class Restplatte(models.Model):
    """
    Restplatte: eigener Datensatz, Preis/Stärke kommen vom Stamm.
    Bestand in STK (jede Restplatte ist normalerweise 1 Stück, aber Buchungen erlauben Logik wie reserviert/freigabe).
    Regal + Platz Pflicht.
    """
    stamm = models.ForeignKey(PlatteStamm, on_delete=models.PROTECT, related_name="restplatten")

    # wird automatisch auf stamm.code gesetzt (kann mehrfach vorkommen)
    code = models.CharField(max_length=80, editable=False)

    laenge_mm = models.PositiveIntegerField()
    breite_mm = models.PositiveIntegerField()

    regal = models.CharField(max_length=50)
    platz = models.CharField(max_length=50)

    bemerkung = models.CharField(max_length=200, blank=True)

    class Meta:
        verbose_name = "Restplatte"
        verbose_name_plural = "Restplatten"
        ordering = ("code", "regal", "platz")
        indexes = [
            models.Index(fields=["code"]),
            models.Index(fields=["regal", "platz"]),
        ]

    def save(self, *args, **kwargs):
        # immer konsistent zum Stamm
        self.code = self.stamm.code
        super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        if self.laenge_mm <= 0 or self.breite_mm <= 0:
            raise ValidationError("Länge und Breite müssen > 0 sein.")
        # Optional: Rest darf nicht größer als Vollformat sein
        if self.laenge_mm > self.stamm.laenge_mm or self.breite_mm > self.stamm.breite_mm:
            raise ValidationError("Restplatte darf nicht größer als Vollformat sein.")

    def __str__(self):
        return f"{self.code} (Rest {self.laenge_mm}x{self.breite_mm})"

    @property
    def staerke_mm(self) -> Decimal:
        return self.stamm.staerke_mm

    @property
    def preis_eur_pro_qm(self) -> Decimal:
        return self.stamm.preis_eur_pro_qm

    @property
    def qm_rest(self) -> Decimal:
        return (Decimal(self.laenge_mm) / Decimal("1000")) * (Decimal(self.breite_mm) / Decimal("1000"))

    @property
    def restpreis(self) -> Decimal:
        return quantize_money(self.qm_rest * self.preis_eur_pro_qm)

    def bestand_physisch_stk(self) -> int:
        qs = self.buchungen.all()
        zugang = sum_int(qs.filter(typ=BuchungsTyp.ZUGANG), "menge_stk")
        abgang = sum_int(qs.filter(typ=BuchungsTyp.ABGANG), "menge_stk")
        korrektur = sum_int(qs.filter(typ=BuchungsTyp.KORREKTUR), "menge_stk")
        return zugang - abgang + korrektur

    def bestand_reserviert_stk(self) -> int:
        qs = self.buchungen.all()
        reserviert = sum_int(qs.filter(typ=BuchungsTyp.RESERVIERT), "menge_stk")
        freigabe = sum_int(qs.filter(typ=BuchungsTyp.FREIGABE), "menge_stk")
        return reserviert - freigabe

    def bestand_verfuegbar_stk(self) -> int:
        return self.bestand_physisch_stk() - self.bestand_reserviert_stk()

    def lagerwert_physisch(self) -> Decimal:
        return quantize_money(Decimal(self.bestand_physisch_stk()) * self.restpreis)


class RestplatteBuchung(BuchungBase):
    restplatte = models.ForeignKey(Restplatte, on_delete=models.CASCADE, related_name="buchungen")
    menge_stk = models.IntegerField(help_text="Ganze Stückzahl. Korrektur darf negativ sein.")

    class Meta(BuchungBase.Meta):
        verbose_name = "Buchung Restplatte"
        verbose_name_plural = "Buchungen Restplatten"

    def clean(self):
        super().clean()
        self.validate_menge_by_typ(self.typ, self.menge_stk, "menge_stk")

    def __str__(self):
        return f"{self.typ} {self.menge_stk} stk | {self.restplatte}"


# -------------------------
# 3) Kantenlager
# -------------------------

class RollenLaenge(models.IntegerChoices):
    L50 = 50, "50 lfm"
    L75 = 75, "75 lfm"
    L150 = 150, "150 lfm"


class Kante(models.Model):
    """
    Kante wird in lfm (ganze Zahl) gebucht.
    Preis Pflicht: EUR/lfm
    Rollenpreis: Rollenlänge * EUR/lfm
    Regal + Platz Pflicht.
    """

    code = models.CharField(max_length=80, help_text="z.B. W1000 ST9")
    staerke_mm = models.DecimalField(max_digits=3, decimal_places=1)  # 0.8 / 1.0 / 2.0
    breite_mm = models.PositiveIntegerField()  # 23 / 33 / 43

    rollenlaenge_lfm = models.IntegerField(choices=RollenLaenge.choices)
    preis_eur_pro_lfm = models.DecimalField(max_digits=10, decimal_places=2)

    regal = models.CharField(max_length=50)
    platz = models.CharField(max_length=50)

    bemerkung = models.CharField(max_length=200, blank=True)

    class Meta:
        verbose_name = "Kante"
        verbose_name_plural = "Kanten"
        ordering = ("code", "staerke_mm", "breite_mm")
        constraints = [
            models.UniqueConstraint(fields=["code", "staerke_mm", "breite_mm"], name="uniq_kante_code_staerke_breite")
        ]
        indexes = [
            models.Index(fields=["code"]),
            models.Index(fields=["regal", "platz"]),
        ]

    def clean(self):
        super().clean()
        # Erlaubte Stärken/Breiten optional hart validieren:
        allowed_staerke = {Decimal("0.8"), Decimal("1.0"), Decimal("2.0")}
        if self.staerke_mm not in allowed_staerke:
            raise ValidationError({"staerke_mm": "Erlaubt: 0.8 / 1.0 / 2.0 mm"})
        if self.breite_mm not in (23, 33, 43):
            raise ValidationError({"breite_mm": "Erlaubt: 23 / 33 / 43 mm"})

    def __str__(self):
        return f"{self.code} | {self.staerke_mm}mm | {self.breite_mm}mm"

    @property
    def rollenpreis(self) -> Decimal:
        return quantize_money(Decimal(self.rollenlaenge_lfm) * self.preis_eur_pro_lfm)

    def bestand_physisch_lfm(self) -> int:
        qs = self.buchungen.all()
        zugang = sum_int(qs.filter(typ=BuchungsTyp.ZUGANG), "menge_lfm")
        abgang = sum_int(qs.filter(typ=BuchungsTyp.ABGANG), "menge_lfm")
        korrektur = sum_int(qs.filter(typ=BuchungsTyp.KORREKTUR), "menge_lfm")
        return zugang - abgang + korrektur

    def bestand_reserviert_lfm(self) -> int:
        qs = self.buchungen.all()
        reserviert = sum_int(qs.filter(typ=BuchungsTyp.RESERVIERT), "menge_lfm")
        freigabe = sum_int(qs.filter(typ=BuchungsTyp.FREIGABE), "menge_lfm")
        return reserviert - freigabe

    def bestand_verfuegbar_lfm(self) -> int:
        return self.bestand_physisch_lfm() - self.bestand_reserviert_lfm()

    def lagerwert_physisch(self) -> Decimal:
        return quantize_money(Decimal(self.bestand_physisch_lfm()) * self.preis_eur_pro_lfm)


class KantenBuchung(BuchungBase):
    kante = models.ForeignKey(Kante, on_delete=models.CASCADE, related_name="buchungen")
    menge_lfm = models.IntegerField(help_text="Ganze lfm. Korrektur darf negativ sein.")

    class Meta(BuchungBase.Meta):
        verbose_name = "Buchung Kante"
        verbose_name_plural = "Buchungen Kanten"

    def clean(self):
        super().clean()
        self.validate_menge_by_typ(self.typ, self.menge_lfm, "menge_lfm")

    def __str__(self):
        return f"{self.typ} {self.menge_lfm} lfm | {self.kante}"


# -------------------------
# 4) Beschlagslager
# -------------------------

class Beschlag(models.Model):
    """
    Beschläge: Bestand in Stück.
    Pflicht: Artikelnummer (unique), Hersteller, Preis, Regal+Platz.
    """

    name = models.CharField(max_length=120)
    artikelnummer = models.CharField(max_length=80, unique=True)
    hersteller = models.CharField(max_length=80)

    preis_eur_pro_stk = models.DecimalField(max_digits=10, decimal_places=2)

    regal = models.CharField(max_length=50)
    platz = models.CharField(max_length=50)

    bemerkung = models.CharField(max_length=200, blank=True)

    class Meta:
        verbose_name = "Beschlag"
        verbose_name_plural = "Beschläge"
        ordering = ("hersteller", "name", "artikelnummer")
        indexes = [
            models.Index(fields=["artikelnummer"]),
            models.Index(fields=["hersteller"]),
            models.Index(fields=["regal", "platz"]),
        ]

    def __str__(self):
        return f"{self.name} ({self.artikelnummer})"

    def bestand_physisch_stk(self) -> int:
        qs = self.buchungen.all()
        zugang = sum_int(qs.filter(typ=BuchungsTyp.ZUGANG), "menge_stk")
        abgang = sum_int(qs.filter(typ=BuchungsTyp.ABGANG), "menge_stk")
        korrektur = sum_int(qs.filter(typ=BuchungsTyp.KORREKTUR), "menge_stk")
        return zugang - abgang + korrektur

    def bestand_reserviert_stk(self) -> int:
        qs = self.buchungen.all()
        reserviert = sum_int(qs.filter(typ=BuchungsTyp.RESERVIERT), "menge_stk")
        freigabe = sum_int(qs.filter(typ=BuchungsTyp.FREIGABE), "menge_stk")
        return reserviert - freigabe

    def bestand_verfuegbar_stk(self) -> int:
        return self.bestand_physisch_stk() - self.bestand_reserviert_stk()

    def lagerwert_physisch(self) -> Decimal:
        return quantize_money(Decimal(self.bestand_physisch_stk()) * self.preis_eur_pro_stk)


class BeschlagBuchung(BuchungBase):
    beschlag = models.ForeignKey(Beschlag, on_delete=models.CASCADE, related_name="buchungen")
    menge_stk = models.IntegerField(help_text="Ganze Stückzahl. Korrektur darf negativ sein.")

    class Meta(BuchungBase.Meta):
        verbose_name = "Buchung Beschlag"
        verbose_name_plural = "Buchungen Beschläge"

    def clean(self):
        super().clean()
        self.validate_menge_by_typ(self.typ, self.menge_stk, "menge_stk")

    def __str__(self):
        return f"{self.typ} {self.menge_stk} stk | {self.beschlag}"
