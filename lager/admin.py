from decimal import Decimal, ROUND_HALF_UP

from django.contrib import admin
from django.db.models import Prefetch

from .models import (
    BuchungsTyp,
    PlatteStamm, PlatteStammBuchung,
    Restplatte, RestplatteBuchung,
    Kante, KantenBuchung,
    Beschlag, BeschlagBuchung,
)


# -------------------------
# Helfer (robust: Feld ODER Methode)
# -------------------------

def val(obj, attrname, default=Decimal("0")):
    """
    Liest ein Attribut, egal ob:
    - Feld/Property (Decimal)
    - Methode (callable)
    """
    v = getattr(obj, attrname, None)
    if v is None:
        return default
    return v() if callable(v) else v


def money(d: Decimal) -> str:
    if d is None:
        d = Decimal("0")
    return f"{Decimal(d).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)} €"


def dec2(d: Decimal) -> Decimal:
    return Decimal(d).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def qm_from_mm(laenge_mm: int, breite_mm: int) -> Decimal:
    # WICHTIG: Decimal-Division, keine Integer-Division
    return (Decimal(laenge_mm) / Decimal("1000")) * (Decimal(breite_mm) / Decimal("1000"))


# ============================================================
# Inlines (Buchungen)
# ============================================================

class PlatteStammBuchungInline(admin.TabularInline):
    model = PlatteStammBuchung
    extra = 0
    fields = ("typ", "menge_stk", "auftragsnummer", "bemerkung", "datum")
    readonly_fields = ("datum",)
    autocomplete_fields = ("platte",)


class RestplatteBuchungInline(admin.TabularInline):
    model = RestplatteBuchung
    extra = 0
    fields = ("typ", "menge_stk", "auftragsnummer", "bemerkung", "datum")
    readonly_fields = ("datum",)
    autocomplete_fields = ("restplatte",)


class KantenBuchungInline(admin.TabularInline):
    model = KantenBuchung
    extra = 0
    fields = ("typ", "menge_lfm", "auftragsnummer", "bemerkung", "datum")
    readonly_fields = ("datum",)
    autocomplete_fields = ("kante",)


class BeschlagBuchungInline(admin.TabularInline):
    model = BeschlagBuchung
    extra = 0
    fields = ("typ", "menge_stk", "auftragsnummer", "bemerkung", "datum")
    readonly_fields = ("datum",)
    autocomplete_fields = ("beschlag",)


# ============================================================
# 1) Stammplatten Admin
# ============================================================

@admin.register(PlatteStamm)
class PlatteStammAdmin(admin.ModelAdmin):
    list_display = (
        "code",
        "staerke_mm",
        "preis_eur_pro_qm_anzeige",
        "plattenpreis_anzeige",
        "bestand_physisch",
        "bestand_reserviert",
        "bestand_verfuegbar",
        "lagerwert",
    )
    search_fields = ("code",)
    inlines = (PlatteStammBuchungInline,)
    ordering = ("code",)

    fieldsets = (
        ("Stammdaten", {"fields": ("code", "staerke_mm")}),
        ("Format (fix)", {"fields": ("laenge_mm", "breite_mm")}),
        ("Preis", {"fields": ("preis_eur_pro_qm",)}),
    )

    def preis_eur_pro_qm_anzeige(self, obj):
        return f"{dec2(val(obj, 'preis_eur_pro_qm'))} € / m²"
    preis_eur_pro_qm_anzeige.short_description = "€/m²"

    def plattenpreis_anzeige(self, obj):
        return money(val(obj, "plattenpreis"))
    plattenpreis_anzeige.short_description = "Plattenpreis"

    def bestand_physisch(self, obj):
        return int(val(obj, "bestand_physisch_stk"))
    bestand_physisch.short_description = "Physisch (Stk)"

    def bestand_reserviert(self, obj):
        return int(val(obj, "bestand_reserviert_stk"))
    bestand_reserviert.short_description = "Reserviert (Stk)"

    def bestand_verfuegbar(self, obj):
        return int(val(obj, "bestand_verfuegbar_stk"))
    bestand_verfuegbar.short_description = "Verfügbar (Stk)"

    def lagerwert(self, obj):
        return money(val(obj, "lagerwert_physisch"))
    lagerwert.short_description = "Lagerwert"


@admin.register(PlatteStammBuchung)
class PlatteStammBuchungAdmin(admin.ModelAdmin):
    list_display = ("platte", "typ", "menge_stk", "auftragsnummer", "datum")
    list_filter = ("typ", "datum")
    search_fields = ("platte__code", "auftragsnummer", "bemerkung")
    autocomplete_fields = ("platte",)
    ordering = ("-datum",)


# ============================================================
# 2) Restplatten Admin
# ============================================================

@admin.register(Restplatte)
class RestplatteAdmin(admin.ModelAdmin):
    list_display = (
        "code",
        "format_anzeige",
        "qm_anzeige",
        "preis_eur_pro_qm_anzeige",
        "restpreis_anzeige",
        "regal",
        "platz",
        "bestand_physisch",
        "bestand_reserviert",
        "bestand_verfuegbar",
        "lagerwert",
    )
    search_fields = ("code", "regal", "platz", "bemerkung", "stamm__code")
    list_filter = ("regal",)
    autocomplete_fields = ("stamm",)
    inlines = (RestplatteBuchungInline,)
    ordering = ("code", "regal", "platz")

    fieldsets = (
        ("Zuordnung", {"fields": ("stamm", "code")}),
        ("Maße (Pflicht)", {"fields": ("laenge_mm", "breite_mm")}),
        ("Lagerplatz (Pflicht)", {"fields": ("regal", "platz")}),
        ("Notiz", {"fields": ("bemerkung",)}),
    )

    def format_anzeige(self, obj):
        return f"{obj.laenge_mm} x {obj.breite_mm} mm"
    format_anzeige.short_description = "Format"

    def qm_anzeige(self, obj):
        qm = qm_from_mm(obj.laenge_mm, obj.breite_mm)
        return f"{qm.quantize(Decimal('0.001'))} m²"
    qm_anzeige.short_description = "m²"

    def preis_eur_pro_qm_anzeige(self, obj):
        # aus Stamm ziehen, egal ob Feld oder Methode
        stamm_preis = val(obj.stamm, "preis_eur_pro_qm")
        return f"{dec2(stamm_preis)} € / m²"
    preis_eur_pro_qm_anzeige.short_description = "€/m² (Stamm)"

    def restpreis_anzeige(self, obj):
        # WICHTIG: hier NICHT über DB rechnen -> sauber Decimal!
        qm = qm_from_mm(obj.laenge_mm, obj.breite_mm)
        stamm_preis = val(obj.stamm, "preis_eur_pro_qm")
        return money((qm * stamm_preis).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    restpreis_anzeige.short_description = "Preis Rest"

    def bestand_physisch(self, obj):
        return int(val(obj, "bestand_physisch_stk"))
    bestand_physisch.short_description = "Physisch (Stk)"

    def bestand_reserviert(self, obj):
        return int(val(obj, "bestand_reserviert_stk"))
    bestand_reserviert.short_description = "Reserviert (Stk)"

    def bestand_verfuegbar(self, obj):
        return int(val(obj, "bestand_verfuegbar_stk"))
    bestand_verfuegbar.short_description = "Verfügbar (Stk)"

    def lagerwert(self, obj):
        # physisch * restpreis
        qm = qm_from_mm(obj.laenge_mm, obj.breite_mm)
        stamm_preis = val(obj.stamm, "preis_eur_pro_qm")
        preis_rest = (qm * stamm_preis).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        phys = Decimal(val(obj, "bestand_physisch_stk"))
        return money((phys * preis_rest).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    lagerwert.short_description = "Lagerwert"


@admin.register(RestplatteBuchung)
class RestplatteBuchungAdmin(admin.ModelAdmin):
    list_display = ("restplatte", "typ", "menge_stk", "auftragsnummer", "datum")
    list_filter = ("typ", "datum")
    search_fields = ("restplatte__code", "auftragsnummer", "bemerkung")
    autocomplete_fields = ("restplatte",)
    ordering = ("-datum",)


# ============================================================
# 3) Kanten Admin
# ============================================================

@admin.register(Kante)
class KanteAdmin(admin.ModelAdmin):
    list_display = (
        "code",
        "staerke_mm",
        "breite_mm",
        "rollenlaenge_lfm",
        "preis_eur_pro_lfm_anzeige",
        "rollenpreis_anzeige",
        "regal",
        "platz",
        "bestand_physisch",
        "bestand_reserviert",
        "bestand_verfuegbar",
        "lagerwert",
    )
    search_fields = ("code", "regal", "platz", "bemerkung")
    list_filter = ("rollenlaenge_lfm", "staerke_mm", "breite_mm", "regal")
    inlines = (KantenBuchungInline,)
    ordering = ("code", "staerke_mm", "breite_mm")

    fieldsets = (
        ("Artikel", {"fields": ("code", "staerke_mm", "breite_mm")}),
        ("Rolle & Preis", {"fields": ("rollenlaenge_lfm", "preis_eur_pro_lfm")}),
        ("Lagerplatz (Pflicht)", {"fields": ("regal", "platz")}),
        ("Notiz", {"fields": ("bemerkung",)}),
    )

    def preis_eur_pro_lfm_anzeige(self, obj):
        return f"{dec2(val(obj, 'preis_eur_pro_lfm'))} € / lfm"
    preis_eur_pro_lfm_anzeige.short_description = "€/lfm"

    def rollenpreis_anzeige(self, obj):
        return money(val(obj, "rollenpreis"))
    rollenpreis_anzeige.short_description = "Rollenpreis"

    def bestand_physisch(self, obj):
        return int(val(obj, "bestand_physisch_lfm"))
    bestand_physisch.short_description = "Physisch (lfm)"

    def bestand_reserviert(self, obj):
        return int(val(obj, "bestand_reserviert_lfm"))
    bestand_reserviert.short_description = "Reserviert (lfm)"

    def bestand_verfuegbar(self, obj):
        return int(val(obj, "bestand_verfuegbar_lfm"))
    bestand_verfuegbar.short_description = "Verfügbar (lfm)"

    def lagerwert(self, obj):
        return money(val(obj, "lagerwert_physisch"))
    lagerwert.short_description = "Lagerwert"


@admin.register(KantenBuchung)
class KantenBuchungAdmin(admin.ModelAdmin):
    list_display = ("kante", "typ", "menge_lfm", "auftragsnummer", "datum")
    list_filter = ("typ", "datum")
    search_fields = ("kante__code", "auftragsnummer", "bemerkung")
    autocomplete_fields = ("kante",)
    ordering = ("-datum",)


# ============================================================
# 4) Beschläge Admin
# ============================================================

@admin.register(Beschlag)
class BeschlagAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "artikelnummer",
        "hersteller",
        "preis_anzeige",
        "regal",
        "platz",
        "bestand_physisch",
        "bestand_reserviert",
        "bestand_verfuegbar",
        "lagerwert",
    )
    search_fields = ("name", "artikelnummer", "hersteller", "regal", "platz", "bemerkung")
    list_filter = ("hersteller", "regal")
    inlines = (BeschlagBuchungInline,)
    ordering = ("hersteller", "name")

    fieldsets = (
        ("Artikel", {"fields": ("name", "artikelnummer", "hersteller")}),
        ("Preis", {"fields": ("preis_eur_pro_stk",)}),
        ("Lagerplatz (Pflicht)", {"fields": ("regal", "platz")}),
        ("Notiz", {"fields": ("bemerkung",)}),
    )

    def preis_anzeige(self, obj):
        return money(val(obj, "preis_eur_pro_stk"))
    preis_anzeige.short_description = "Preis/Stk"

    def bestand_physisch(self, obj):
        return int(val(obj, "bestand_physisch_stk"))
    bestand_physisch.short_description = "Physisch (Stk)"

    def bestand_reserviert(self, obj):
        return int(val(obj, "bestand_reserviert_stk"))
    bestand_reserviert.short_description = "Reserviert (Stk)"

    def bestand_verfuegbar(self, obj):
        return int(val(obj, "bestand_verfuegbar_stk"))
    bestand_verfuegbar.short_description = "Verfügbar (Stk)"

    def lagerwert(self, obj):
        return money(val(obj, "lagerwert_physisch"))
    lagerwert.short_description = "Lagerwert"


@admin.register(BeschlagBuchung)
class BeschlagBuchungAdmin(admin.ModelAdmin):
    list_display = ("beschlag", "typ", "menge_stk", "auftragsnummer", "datum")
    list_filter = ("typ", "datum")
    search_fields = ("beschlag__artikelnummer", "beschlag__name", "auftragsnummer", "bemerkung")
    autocomplete_fields = ("beschlag",)
    ordering = ("-datum",)
