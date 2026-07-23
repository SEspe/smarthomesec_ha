================================================================================
login_probe.py - which host + password scheme does the login accept?
================================================================================

THE PROBLEM
-----------
A new app shipped new credentials and the integration can no longer log in.
The natural suspicion is a new API endpoint - but that is almost never it.

Measured on 2026-07-23:

  - smartalarm.alarm24.no, portal.vestasecurity.eu and smarthomesec.bydemes.com
    ALL resolve to the same IP (52.31.23.137) and all serve /REST/v2. They are
    branded front-ends onto one shared Climax backend (SNI virtual-hosting, each
    with its own valid TLS cert). The "portal.vestasecurity.eu/vesta/" path that
    turns up in web searches is a web-UI/marketing path and 404s as an API base;
    the real API is /REST/v2 on every one of these hosts.

  - A bad-credential login always returns the same generic body,
    {"code":"010","result":false,"message":"Login failure!"}, no matter WHY it
    failed. So you cannot tell a wrong endpoint from a wrong password hash from a
    wrong username format by looking at one response.

What actually changes between app versions is usually the login PAYLOAD, most
often the password encoding. The integration currently sends (see
custom_components/smarthomesec/__init__.py::login):

    account=<user>&password=<md5(pw)>&pw_encrypted=hashed&login_entry=web

This probe tries the real credentials against a short, ordered list of payload
variants and tells you which one - if any - returns a token.

Requirements: Python 3.7+, standard library only. Nothing to install.


--------------------------------------------------------------------------------
THE RATE LIMIT (the single most important thing to know)
--------------------------------------------------------------------------------
The server throttles by SOURCE IP, not by account. After only ~3 failed
attempts it returns:

    code 018  "login failed too many times!"
    code 044  "Retry after 5 minutes due to multiple errors."

This was observed against a NON-existent account, so having the right password
does not shield you while probing. The tool is built around this:

  - The DEFAULT run tries one host and the three most-likely schemes = exactly
    3 attempts, which fits inside one 5-minute window.
  - It STOPS the instant it sees a lockout code, so it never digs deeper.
  - --all-schemes and --all-hosts deliberately exceed one window; use them only
    across separate 5-minute windows, or expect a partial run.
  - If your md5 credentials are in fact correct, attempt 1 succeeds and no
    lockout is ever reached. Lockout only bites when the scheme truly differs.


--------------------------------------------------------------------------------
RUNNING IT
--------------------------------------------------------------------------------
From any machine with Python and internet (it talks only to the alarm hosts):

    py login_probe.py --user YOUR_ACCOUNT
        Prompts for the password (hidden), tries smartalarm.alarm24.no with the
        three core schemes. This is the one to run first.

    py login_probe.py --user YOUR_ACCOUNT --all-schemes
        Adds sha256 and md5-upper. 5 attempts - will hit the rate limit; run it
        in a fresh window, on its own.

    py login_probe.py --user YOUR_ACCOUNT --all-hosts
        Tries all three hosts. Only worth it if you suspect the account lives on
        a different regional server; otherwise the host does not matter.

    py login_probe.py --user YOUR_ACCOUNT --also-app
        Also tries login_entry=app instead of web.

    --host HOST        try a specific host (repeatable); overrides the defaults
    --delay SECONDS    pause between attempts (default 1.0)
    --out PATH         also write the report to a file (the PASSWORD is never
                       written - only host/scheme/result lines)

PASSWORD HANDLING
The password is read with getpass (hidden, not echoed, not in shell history) by
default. --password PW and --password-stdin exist for scripting; --password
lands in your shell history, so prefer the prompt or --password-stdin. The
password is sent ONLY to the alarm host over HTTPS and is never logged or
written to --out.


--------------------------------------------------------------------------------
READING THE OUTPUT
--------------------------------------------------------------------------------
Each attempt prints one line:

    OK   ...  -> token abc123…7f9      a variant was accepted (probe stops here)
    --   ...  -> code=010 'Login failure!'   normal rejection, keep trying
    !!   ...  -> code=044 ... (rate-limited)  locked out, probe stops
    ??   ...  -> network error: ...          could not reach the host

On success the summary spells out exactly what to change:

    SUCCESS - a variant was accepted:
        host        = smartalarm.alarm24.no
        login_entry = web
        password    = plaintext
    -> const.py host is correct; the login recipe was the issue
    -> the working scheme is 'plaintext', not the integration's md5 —
       the login payload in __init__.py::login needs updating.

Four possible conclusions:

  SUCCESS       -> apply the printed host / scheme / login_entry to the code.
  RATE-LIMITED  -> inconclusive; untried variants remain. Wait 5 min, re-run.
  NO variant    -> every host REPLIED and rejected the creds. The endpoint and
                   scheme are fine; the credentials/username format are the
                   problem, or the account is not provisioned on these hosts.
  NO host reached -> pure connectivity/DNS/firewall issue; not about creds.


--------------------------------------------------------------------------------
ONCE YOU KNOW
--------------------------------------------------------------------------------
- Different host  -> set API_BASEHOST in custom_components/smarthomesec/const.py
                     (no trailing slash; callers add the separator).
- Different scheme -> update the password encoding in __init__.py::login (it
                      currently does hashlib.md5(...).hexdigest() with
                      pw_encrypted="hashed").
- Different login_entry -> change the "login_entry": "web" field in that same
                           payload.


--------------------------------------------------------------------------------
STATUS
--------------------------------------------------------------------------------
Written 2026-07-23. The host mapping, the shared 52.31.23.137 IP, the /REST/v2
path on all three hosts, and the code 010 / 018 / 044 rate-limit behaviour were
all measured live against the servers. The request/parse path is verified end to
end (wrong credentials correctly return code 010). The SUCCESS path has NOT been
exercised - that needs a valid account, which is yours to supply. If the winning
line looks wrong, the report prints the raw code and message for every attempt
so you can see exactly what the server said.
