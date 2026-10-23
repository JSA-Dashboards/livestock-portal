"""
The client deployment's main file. Same portal, same fifteen dashboards, same
landing grid — with the working tools, the raw data tabs and the method
furniture taken out, and no staff door on it at all.

WHY A SECOND MAIN FILE RATHER THAN A SECOND SECRET. Streamlit Cloud takes the
main file path per app, so which view a deployment serves is decided by how it
is wired up rather than by a value somebody has to remember to set. A
`PORTAL_VIEW` secret would have to default to STAFF — otherwise the existing
app would strip itself the first time it rebooted after this shipped — and a
client deployment that lost that secret would then come up quietly serving the
analyst view to clients. There is no such state here: this file sets the flag
before anything renders, and it cannot be deployed without being pointed at.

WHY IT RUNS Home.py RATHER THAN IMPORTING IT. Streamlit re-executes the main
script on every rerun, and `import Home` would be a cached no-op from the
second rerun onward — the page would render once and then come up blank.
`runpy.run_path` reads and executes the file each time, which is also what
makes the file watcher pick up an edit to Home.py here.

WHY IT RUNS Home.py AT ALL, rather than holding its own grid: there is exactly
one copy of DASHBOARDS, one copy of the tile CSS and one copy of the layout
arithmetic, so the client landing page cannot drift away from the staff one.
Keeping the shell in Home.py also keeps it where this repo's tests already read
it from.

To deploy: a second Streamlit Cloud app in the `jsa-dashboards` workspace, same
repo, branch `master`, **main file `Client.py`**. It needs its own copy of this
app's secrets — the Snowflake block (and NO `SNOWFLAKE_SCHEMA`), `MARS_API_KEY`,
`NASS_API_KEY`, `MASSIVE_API_KEY`. It does NOT need `ANTHROPIC_API_KEY`,
`CHAT_PASSPHRASE`, `ADMIN_PASSPHRASE` or `REPORTS_PASSPHRASE`: the Ask AI tab
and the staff tools are not reachable from this view, and leaving the admin
passphrase off is one more reason a client deployment cannot be talked into the
staff view.
"""
import runpy
from pathlib import Path

import portal_view

# Before anything renders, and before Home.py's own imports pull in a page.
portal_view.set_client()

_HOME = Path(__file__).with_name("Home.py")
runpy.run_path(str(_HOME), run_name="__main__")
