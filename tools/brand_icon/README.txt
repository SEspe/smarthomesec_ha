================================================================================
make_icon.py - regenerate the integration's brand icon
================================================================================

WHAT THIS IS
------------
The integration ships its own brand images in
custom_components/smarthomesec/brand/. Home Assistant 2026.3+ serves those
locally via /api/brands/integration/smarthomesec/<image> and they take priority
over the brands CDN, so no PR to home-assistant/brands is needed. On older HA
the folder is simply ignored and the tile stays blank as before.

Files HA looks for (all PNG):

    icon.png        256x256    <- the one the integrations list uses
    icon@2x.png     512x512
    dark_icon.png   256x256    <- used when the dark theme is active
    dark_icon@2x.png 512x512
    logo.png / dark_logo.png (+ @2x) are optional wordmarks; we ship none,
    HA falls back to the icon.

THE ARTWORK
-----------
Original artwork - a shield with a house and an "armed" indicator dot - drawn
in code, not a vendor logo. That is deliberate: SmartHomeSec / Vesta / alarm24
logos belong to those companies, and this is an unofficial fork.

    light theme shield  #17547E
    dark theme shield   #388DC6   (same hue lifted, so it does not sink into
                                   HA's dark card)
    house               white
    indicator dot       #FFB020

Drawn at 4x and downscaled with LANCZOS, because PIL's polygon fill has no
antialiasing. The shield outline is two quadratic beziers with the control
point high on the side - that keeps the taper straight for longer, which is
what makes it read as a shield instead of a rounded badge.

RUNNING IT
----------
    ./.venv/Scripts/python.exe tools/brand_icon/make_icon.py

It writes icon.png, icon@2x.png, dark_icon.png, dark_icon@2x.png and a
preview.png next to the script. preview.png is the useful part: it renders the
icon at 140/64/40/32/24 px on both an HA light card and a dark one, including a
mock integrations-list row, because the only size that really matters is the
small one. Copy the four icons into custom_components/smarthomesec/brand/ when
you are happy with them; preview.png is not shipped.

CHANGING IT
-----------
Colours are constants at the top. Geometry lives in shield_points() and
house_points(), both in fractions of the canvas, so it scales cleanly. Keep the
margin small - HA does not trim for you, and empty edges make the icon look
smaller than its neighbours in the list.
