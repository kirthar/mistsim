"""CSS compartido por las dos páginas: paleta clara/oscura y layout responsive.

Todo vía `prefers-color-scheme`, sin JavaScript para el tema: las páginas se abren con
`file://`, muchas veces sin que nadie las mire dos veces, así que el modo del sistema
operativo basta y evita depender de `localStorage` (que en `file://` es delicado: cada
fichero puede caer en un origen distinto según el navegador).
"""
from __future__ import annotations

BASE_CSS = """
:root{
  --bg:#f5f4f1; --bg-alt:#ffffff; --ink:#1c1a17; --ink-dim:#6b665e;
  --border:#ded9d0; --accent:#8a5a2b; --accent-ink:#ffffff;
  --ok:#3f7d4a; --warn:#b3541e; --bad:#a23b3b;
  --metal-ready:#3f7d4a; --metal-burned:#8a5a2b; --metal-flared:#a23b3b;
  --shadow:0 1px 3px rgba(0,0,0,.08);
  --font: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
  --mono: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}
@media (prefers-color-scheme: dark){
  :root{
    --bg:#171512; --bg-alt:#211e1a; --ink:#efe9df; --ink-dim:#a89f8f;
    --border:#3a352c; --accent:#d99a53; --accent-ink:#211e1a;
    --ok:#6bbf75; --warn:#e0904a; --bad:#e07171;
    --metal-ready:#6bbf75; --metal-burned:#d99a53; --metal-flared:#e07171;
    --shadow:0 1px 3px rgba(0,0,0,.4);
  }
}
*{box-sizing:border-box}
html,body{margin:0;padding:0}
body{
  background:var(--bg); color:var(--ink); font-family:var(--font);
  line-height:1.45; font-size:15px;
}
a{color:var(--accent)}
h1,h2,h3{line-height:1.2}
header.page{
  padding:1rem 1.25rem; border-bottom:1px solid var(--border); background:var(--bg-alt);
  display:flex; flex-wrap:wrap; gap:.75rem 1.5rem; align-items:baseline;
}
header.page h1{font-size:1.15rem; margin:0}
header.page nav a{margin-right:1rem; font-size:.9rem; text-decoration:none}
header.page nav a:hover{text-decoration:underline}
.notice{
  background:var(--bg-alt); border:1px solid var(--warn); border-left-width:4px;
  border-radius:4px; padding:.6rem .9rem; margin:.75rem 1.25rem; font-size:.88rem;
  color:var(--ink);
}
.notice b{color:var(--warn)}
main{padding:1rem 1.25rem 3rem; max-width:1400px; margin:0 auto}
.card-box{
  background:var(--bg-alt); border:1px solid var(--border); border-radius:8px;
  box-shadow:var(--shadow);
}
button, select, input[type=text], input[type=number]{
  font:inherit; color:var(--ink); background:var(--bg-alt); border:1px solid var(--border);
  border-radius:6px; padding:.35rem .55rem;
}
button{cursor:pointer}
button:hover{border-color:var(--accent)}
button.primary{background:var(--accent); color:var(--accent-ink); border-color:var(--accent)}
button:disabled{opacity:.4; cursor:default}
.pill{
  display:inline-block; border:1px solid var(--border); border-radius:999px;
  padding:.05rem .55rem; font-size:.78rem; color:var(--ink-dim);
}
.mono{font-family:var(--mono)}
.scroll-x{overflow-x:auto}
table{border-collapse:collapse; width:100%}
th,td{padding:.3rem .5rem; text-align:left; border-bottom:1px solid var(--border)}
footer.page{padding:1.5rem 1.25rem; color:var(--ink-dim); font-size:.82rem; text-align:center}
"""
