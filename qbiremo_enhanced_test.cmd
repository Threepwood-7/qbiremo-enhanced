@echo off

CD /D %~dp0

python -m pytest -q
