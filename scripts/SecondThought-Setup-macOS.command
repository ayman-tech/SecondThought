#!/bin/sh
# Double-click setup for macOS. It runs install.sh from GitHub, the same as
# pasting the Terminal command from the website.
echo "Setting up SecondThought. The first time takes about 5 minutes."
echo
curl -fsSL https://raw.githubusercontent.com/ayman-tech/SecondThought/master/scripts/install.sh | sh
echo
printf 'Press Return to close this window.'
read -r _
