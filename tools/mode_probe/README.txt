mode_probe - how does panel/mode treat the PIN?
================================================

THE QUESTION
------------
PR #20 asks to rename the arming payload's PIN field from `pincode` to `pin`,
because on the contributor's panel `pincode` returned HTTP 400 and `pin` was
accepted. Both panels sit on portal.vestasecurity.eu, so "different tenant"
does not explain it.

A deliberate wrong-PIN arm on 2026-09-22 then measured this:

    pincode=<correct>  ->  HTTP 200 {"result":true,"code":"000"}  -> armed
    pincode=<wrong>    ->  HTTP 400                               -> nothing

So the server DOES validate the PIN, and it reports a bad one as a 400 - which
no other part of this API does (everything else is HTTP 200 with a `code` other
than "000"). That matters, because it means a 400 here is evidence about the
PIN rather than about the request's shape, and it raises the question this
probe answers:

    If the server validates `pincode`, what happens when `pincode` is ABSENT?
    Because that is precisely what renaming the field to `pin` does.

If arming succeeds with no `pincode`, then `pin` is not the correct spelling -
it is an unrecognised field, and the rename works by BYPASSING THE PIN CHECK.
That is a security regression, not a fix.


RUNNING IT
----------
Python 3.7+, standard library only. Nothing to install.

    cd tools\mode_probe
    py mode_probe.py --user YOUR_ACCOUNT

or double-click run.cmd, which prompts for the account and does the same.

NOTE THE .\ IF YOU TYPE IT IN A CMD WINDOW:

    .un.cmd YOUR_ACCOUNT --out result.txt

Windows can be configured with NoDefaultCurrentDirectoryInExePath=1, which
stops cmd searching the current directory for a program. On such a machine a
bare `run.cmd` gives "'run.cmd' is not recognized as an internal or external
command" even while you are standing in this folder. `.un.cmd` always works,
and so does calling the script directly with `py`.

See the payload matrix without touching the network or your alarm:

    py mode_probe.py --user YOUR_ACCOUNT --dry-run

Useful flags:

    --host HOST          default portal.vestasecurity.eu
    --area N             default 1
    --mode home|arm      which arm mode to test (default: home)
    --skip-wrong-pin     leave out step E
    --yes                skip the confirmation prompt
    --out result.txt     write the report (contains no PIN and no token)


WHY HOME AND NOT AWAY
---------------------
`home` is the default on purpose, and there is no reason to change it. It arms
the perimeter without live interior zones or an exit delay, so walking past a
PIR while the probe runs cannot set anything off.

It costs nothing in evidence either. The PIN is validated by panel/mode the
same way whichever mode you ask for, and the two measurements this whole probe
is built on were both home-mode:

    18:44:37  pincode=<correct>  mode=home  ->  200/000  ->  armed, CID 3456
    18:58:43  pincode=<wrong>    mode=home  ->  400      ->  nothing

So the probe tests exactly the configuration we already have a baseline for.
`--mode arm` exists, but it adds an exit delay and live interior zones for no
extra information.

WHAT IT SENDS
-------------
One login, then arm attempts, disarming after each one that actually arms,
and restoring the mode it found at the start:

    A  pincode=<correct>              baseline - what the integration does
    B  pin=<correct>                  is `pin` accepted at all?
    C  pin + pincode, both correct    is a both-keys fallback viable?
    D  (no PIN field whatsoever)      does it arm with NO pin?  <- the key test
    E  pin=<wrong>                    if this ARMS, `pin` is ignored entirely

Reading the result:

    D armed   -> the panel arms with no PIN, so `pin` is equivalent to omitting
                 it. PR #20's patch removes the check. Do not merge it.
    E armed   -> the same conclusion from the other side.
    B armed, D and E rejected -> the server really does accept `pin` too, and
                 the disagreement is a genuine per-panel difference.
    C armed   -> sending both keys is safe, and is the compatible fix.
    A is the control. If A fails, something else is wrong - stop and re-read.


BEFORE YOU RUN IT - THIS IS A REAL ALARM
----------------------------------------
  * Every successful step ARMS THE PANEL and then disarms it. Each transition
    sends a Contact ID open/close record to your alarm company's receiving
    centre. They are not alarms, but they are on your account's record. If
    that matters, tell them first.

  * Step E sends a deliberately WRONG PIN. Login is rate-limited per SOURCE IP
    (~3 failures -> code 018/044, locked out 5 minutes). Whether panel/mode
    shares that counter is unmeasured, so the probe sends at most one wrong
    PIN. --skip-wrong-pin leaves it out entirely.

  * The probe restores the mode it found at startup. If you interrupt it
    partway, CHECK YOUR PANEL - it may be left armed.

  * --dry-run makes no network request at all and prompts for nothing. Use it
    first if you want to see exactly what would be sent.


WHAT IT NEVER DOES
------------------
Your password and PIN are read interactively (getpass), sent only to the alarm
host over HTTPS, and never printed, logged or written to --out. The report and
the console output carry neither the PIN nor the session token.
