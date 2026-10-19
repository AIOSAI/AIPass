#!/usr/bin/env bash
# The README demo: three read-only drone commands, typed at a fake prompt.
# Recorded with: asciinema rec -c ./demo.sh demo.cast ; rendered with agg.
# Runs from the orchestrator's seat, found relative to this file, so drone reads a passport.
set -u
cd "$(dirname "$(readlink -f "$0")")/../src/aipass/devpulse"

prompt() { printf '\033[1;32m$\033[0m '; }

type_cmd() {
  prompt
  local s="$1"
  for ((i = 0; i < ${#s}; i++)); do
    printf '%s' "${s:$i:1}"
    sleep 0.035
  done
  sleep 0.5
  printf '\n'
}

fresh() { printf '\033[2J\033[H'; }

fresh
sleep 0.6
type_cmd 'drone systems'
drone systems 2>&1 | head -22
sleep 2.4

fresh
type_cmd 'drone @memory search "tests pass serially but fail under xdist" --n 1'
drone @memory search "tests pass serially but fail under xdist" --type local --n 1 2>&1 | grep -v -E "model loading|^Type:"
sleep 3

fresh
type_cmd 'drone @seedgo audit aipass @cli'
drone @seedgo audit aipass @cli 2>&1 | sed -n '2,24p'
sleep 3
printf '\n'
prompt
sleep 1.5
