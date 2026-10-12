event_probe - read the panel's event log from the event/report endpoint
=======================================================================

READ-ONLY. It logs in once and reads. It never arms, disarms or changes
anything on the panel.


WHY
---
The integration sees two records from panel/cycle: the latest alarm
(alarm_event_latest) and the latest event of any kind (report_event_latest).
Everything between two refreshes is gone. So what the panel emitted around
each alarm we have on record is only known where a debug log happened to be
running.

Yale's open-source client for the same Climax backend reads a paged event
log at /api/event/report/?page_num=1&set_utc=1. Nobody has tried it on Vesta.
If it is there, it answers, after the fact:

  - Does the panel ever emit a 3130 RESTORE after an alarm? The integration
    has a branch for it that the logs so far suggest never fires.
  - What was emitted around the 2026-08-04, 2026-08-16 and 2026-09-06
    burglaries, in order?
  - Does the server's own device name agree with the integration's
    zone-to-device mapping?

And if the endpoint is NOT there, that is a result too.


RUN IT
------
Windows, from this folder - note the .\ in front:

    .\run.cmd
    .\run.cmd you@example.com --pages 10

run.cmd writes result.txt (the report) and raw.out (the raw pages, token
removed). Both are gitignored.

Or directly, from anywhere:

    py event_probe.py --user you@example.com
    py event_probe.py --user you@example.com --dry-run      # shows URLs, sends nothing
    py event_probe.py --user you@example.com --pages 10 --out result.txt --raw raw.out
    py event_probe.py --user you@example.com --no-set-utc   # compare time fields

Python 3.7+, standard library only.

On a Windows machine with NoDefaultCurrentDirectoryInExePath set, a bare
"run.cmd" reports "not recognized" even in its own folder. Use .\run.cmd.


BEFORE YOU RUN IT
-----------------
  * One login. Login is rate-limited per source IP: about 3 failed attempts
    locks you out for 5 minutes. A mistyped password costs one of them.

  * Logging in invalidates the token Home Assistant is using. The server drops
    HA's WebSocket about 1.5 s later and the integration reconnects on its own.
    Expect a short gap in real-time updates - by the code path, about 25 s
    (two token errors, then a fresh login); not measured. The next
    REST poll catches up on anything missed. Don't run it in the middle of
    something you are relying on HA to notice.

  * result.txt and raw.out contain YOUR event history: times, device names,
    zones. The token is removed from both. Read raw.out before sharing it.


WHAT IT DOES
------------
  1. Tries "event/report" then "event/report/" and uses the first that
     answers HTTP 200 with JSON.
  2. Prints the reply's SHAPE - top-level keys and one event's keys, never
     values. The shape on Vesta is the main unknown.
  3. Reads up to --pages pages (default 5) and prints one line per event:
     time, report_id, Contact ID code, ALARM/restore class, meaning, area,
     zone, user and the server's device name. Known burglary records are
     flagged when they appear.
  4. A summary: how many alarm-class, restore and cancel events, which of the
     three known burglaries are still in the log, and the last event read.

Time is shown from the `time` field. On Vesta that is the PANEL's clock, in
local time, formatted DD/MM/YYYY HH:MM:SS - even with set_utc=1. The panel's
clock runs slow (~185 s by October 2026), so an alarm can appear to happen
before the arming that preceded it. Use these times for ORDER, not for when.


WHAT IT FOUND (2026-10-12, Vesta, first run)
--------------------------------------------
  * The endpoint exists: HTTP 200, code 000.
  * It ignores page_num and returns one event: the latest alarm, with
    "read": false. It looks like the app's alarm notification, not a history
    log. Paging parameters that do work are still unknown.
  * Fields differ from Yale: `id` instead of report_id, string times, plus
    is_alarm, read, type, cid_trans ("Innbrudd"), user_trans ("IR Stue
    (Sone 5)"), area_trans, cid_icon, cid_source.
  * Text is not UTF-8: area_trans arrives as Latin-1/Windows-1252.


READING THE RESULT
------------------
  * "No candidate answered with JSON"  -> not exposed on this tenant. Note the
    HTTP status and body it printed; a 404 and a 403 mean different things.
  * restores > 0  -> the panel does send restores, and the integration's
    restore branch can fire. 0 across alarms that are in range -> it cannot.
  * A known burglary "found"  -> compare the events around it with the
    timelines in docs/VESTA_API.md.
  * Event keys that differ from Yale's (report_id, cid, event_type, user,
    area, zone, name, time, cid_source) are worth writing down as they are.
