Output "docs/assets/demo-health.gif"

Set Theme "Catppuccin Mocha"
Set FontSize 13
Set Width 900
Set Height 820
Set Padding 20
Set WindowBar "Colorful"
Set BorderRadius 10
Set TypingSpeed 35ms

Hide
Type "export PS1='➜ '; export PATH=$PWD/.venv/bin:$PATH; unset VIRTUAL_ENV; clear"
Enter
Sleep 200ms
Show

Type "tff health --project examples/minimal-sqlmesh-project"
Sleep 500ms
Enter
Sleep 5s
