"""The local studio: `kaosctl dev`, `kaosctl step run` and `kaosctl build` (PRD novelcore/kaos#1682, phase 2).

Why: a client should be able to set up, try and build one step of their pipeline on their own machine, with one command
each, without knowing Docker and without access to the platform's cluster. `kaosctl` only detects, verifies and suggests:
it never installs system software (D-17, CON-17) and never copies a platform secret (CON-16).

Modules: `steps` (find the steps), `deps` (read a step's dependencies statically), `pyenv` + `dev` (one virtual
environment per step), `vscode` (the interpreter hint), `run` + `workmap` + `envallow` + `sample` (run one step),
`engine` + `suggest` + `engine_errors` + `build` (build the image), `proc` (the only place a program is started),
`cli` (the commands).
"""
