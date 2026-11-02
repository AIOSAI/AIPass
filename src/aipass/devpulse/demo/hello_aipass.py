#!/usr/bin/env python3
"""
AIPass Hello World — A fancy terminal demo.

Shows off the AIPass multi-agent ecosystem with a live animated dashboard.
Built by @devpulse as a demo for friends.
"""

import time
import random
import sys
from datetime import datetime

# ── ANSI Colors ──────────────────────────────────────────────────────
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
MAGENTA = "\033[35m"
BLUE = "\033[34m"
WHITE = "\033[97m"
RED = "\033[31m"
BG_DARK = "\033[48;5;235m"
CLEAR = "\033[2J\033[H"

# ── Branch Data ──────────────────────────────────────────────────────
BRANCHES = [
    ("drone", "Command Router", "Routes commands to branches", CYAN),
    ("sentry", "Standards Engine", "21-standard compliance pack", GREEN),
    ("prax", "Logging System", "Stack-aware dual routing", YELLOW),
    ("cli", "CLI Framework", "Argument parsing & registry", BLUE),
    ("flow", "Plan Manager", "FPLANs + DPLANs", MAGENTA),
    ("ai_mail", "Communications", "Inter-branch email & dispatch", CYAN),
    ("api", "LLM Access Layer", "OpenRouter, multi-provider", GREEN),
    ("trigger", "Event System", "12 events, error registry", YELLOW),
    ("spawn", "Branch Lifecycle", "Create, update, delete", BLUE),
    ("memory", "Memory Bank", "ChromaDB vector search", MAGENTA),
    ("devpulse", "Orchestration Hub", "You are here", CYAN),
]

ACTIVITIES = [
    "Processing dispatch...",
    "Running sentry audit...",
    "Indexing memories...",
    "Routing command...",
    "Checking standards...",
    "Syncing mailbox...",
    "Updating passport...",
    "Logging event...",
    "Refreshing dashboard...",
    "Scanning for changes...",
    "Compiling plan status...",
    "Waking branch agent...",
]


def print_slow(text, delay=0.02):
    """Print text character by character for dramatic effect."""
    for char in text:
        sys.stdout.write(char)
        sys.stdout.flush()
        time.sleep(delay)
    print()


def draw_box(title, content_lines, width=60, color=CYAN):
    """Draw a bordered box with title."""
    print(f"  {color}┌{'─' * (width - 2)}┐{RESET}")
    print(f"  {color}│{RESET} {BOLD}{WHITE}{title.center(width - 4)}{RESET} {color}│{RESET}")
    print(f"  {color}├{'─' * (width - 2)}┤{RESET}")
    for line in content_lines:
        padded = f"{line:<{width - 4}}"[: width - 4]
        print(f"  {color}│{RESET} {padded} {color}│{RESET}")
    print(f"  {color}└{'─' * (width - 2)}┘{RESET}")


def animate_startup():
    """Animated boot sequence."""
    print(CLEAR)
    print()

    # ASCII art title
    title = f"""
  {CYAN}{BOLD}     █████╗ ██╗██████╗  █████╗ ███████╗███████╗
      ██╔══██╗██║██╔══██╗██╔══██╗██╔════╝██╔════╝
      ███████║██║██████╔╝███████║███████╗███████╗
      ██╔══██║██║██╔═══╝ ██╔══██║╚════██║╚════██║
      ██║  ██║██║██║     ██║  ██║███████║███████║
      ╚═╝  ╚═╝╚═╝╚═╝     ╚═╝  ╚═╝╚══════╝╚══════╝{RESET}
    """
    print(title)
    time.sleep(0.5)

    print_slow(f"  {DIM}Multi-Agent Framework — Where AI Citizens Live{RESET}", 0.03)
    print()
    time.sleep(0.3)

    # Boot sequence
    steps = [
        ("Initializing drone router", 0.4),
        ("Loading 11 branch identities", 0.3),
        ("Connecting AI Mail network", 0.3),
        ("Mounting .trinity/ memories", 0.4),
        ("Starting Prax logging", 0.2),
        ("Sentry standards: 33 loaded", 0.3),
        ("System ready", 0.1),
    ]

    for step, duration in steps:
        sys.stdout.write(f"  {DIM}[{YELLOW}...{DIM}]{RESET} {step}")
        sys.stdout.flush()
        time.sleep(duration)
        sys.stdout.write(f"\r  {DIM}[{GREEN} ✓ {DIM}]{RESET} {step}\n")
        sys.stdout.flush()

    time.sleep(0.5)
    print()


def show_branch_grid():
    """Display all branches in a nice grid."""
    print(f"  {BOLD}{WHITE}┌─ REGISTERED BRANCHES {'─' * 36}┐{RESET}")
    print()

    for name, role, _, color in BRANCHES:
        status = "●" if random.random() > 0.1 else "○"
        status_color = GREEN if status == "●" else RED

        bar_len = random.randint(2, 12)
        bar = f"{'█' * bar_len}{'░' * (12 - bar_len)}"

        is_devpulse = " ◀ YOU" if name == "devpulse" else ""

        print(
            f"  {status_color}{status}{RESET} {color}{BOLD}@{name:<10}{RESET} {DIM}{role:<18}{RESET} {CYAN}{bar}{RESET}{YELLOW}{is_devpulse}{RESET}"
        )
        time.sleep(0.08)

    print()
    print(f"  {BOLD}{WHITE}└{'─' * 58}┘{RESET}")
    print()


def show_live_activity():
    """Simulate live system activity for a few seconds."""
    print(f"  {BOLD}{WHITE}── LIVE ACTIVITY ──{RESET}")
    print()

    for _ in range(8):
        branch = random.choice(BRANCHES)
        activity = random.choice(ACTIVITIES)
        timestamp = datetime.now().strftime("%H:%M:%S")

        print(f"  {DIM}{timestamp}{RESET} {branch[3]}@{branch[0]:<10}{RESET} {activity}")
        time.sleep(0.4)

    print()


def show_dispatch_demo():
    """Simulate a dispatch cycle."""
    print(f"  {BOLD}{WHITE}── DISPATCH DEMO ──{RESET}")
    print()

    # Simulate sending
    print_slow(f'  {CYAN}📤 drone @ai_mail send @spawn "Build greeting module" --dispatch{RESET}', 0.02)
    time.sleep(0.5)
    print(f"  {GREEN}   ✓ Email dispatched to @spawn{RESET}")
    time.sleep(0.3)

    print_slow(f"  {CYAN}🔔 drone @ai_mail dispatch wake @spawn{RESET}", 0.02)
    time.sleep(0.5)
    print(f"  {GREEN}   ✓ @spawn is awake and processing...{RESET}")
    time.sleep(0.8)

    # Simulate work
    work_steps = [
        "Reading inbox...",
        "Found dispatch: 'Build greeting module'",
        "Creating FPLAN-0099...",
        "Deploying build agent...",
        "Writing src/aipass/spawn/apps/handlers/greeting.py...",
        "Running sentry audit... 100% compliant",
        "Emailing results back to @devpulse...",
    ]

    for step in work_steps:
        sys.stdout.write(f"  {DIM}  ↳ {step}{RESET}")
        sys.stdout.flush()
        time.sleep(0.5)
        print()

    print()
    print(f'  {GREEN}{BOLD}  📨 Reply from @spawn: "Greeting module built. 12 tests passing."{RESET}')
    print()


def show_stats():
    """Final stats box."""
    stats = [
        f"{WHITE}Branches:    {CYAN}11 registered, 11 operational{RESET}",
        f"{WHITE}Standards:   {GREEN}33 sentry checks active{RESET}",
        f"{WHITE}Sessions:    {YELLOW}86 completed (devpulse alone){RESET}",
        f"{WHITE}Architecture:{MAGENTA} Citizens + Agents + Dispatch{RESET}",
        f"{WHITE}Built with:  {CYAN}Python, Rich, Claude Code{RESET}",
        f"{WHITE}Memory:      {GREEN}.trinity/ — persistent identity{RESET}",
    ]
    draw_box("SYSTEM STATS", stats, 56, CYAN)


def main():
    """Run the full demo."""
    try:
        animate_startup()
        show_branch_grid()
        time.sleep(0.5)
        show_live_activity()
        time.sleep(0.5)
        show_dispatch_demo()
        time.sleep(0.5)
        show_stats()

        print()
        print_slow(f"  {BOLD}{CYAN}AIPass{RESET}{DIM} — Where AI citizens live, work, and remember.{RESET}", 0.03)
        print()

    except KeyboardInterrupt:
        print(f"\n\n  {DIM}Demo interrupted. Goodbye!{RESET}\n")


if __name__ == "__main__":
    main()
