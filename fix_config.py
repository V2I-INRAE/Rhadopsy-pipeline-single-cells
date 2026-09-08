import re
import sys
from pathlib import Path

# Report these patterns for manual review; do not change them automatically.
DEF_RE = re.compile(r"(?m)^\s*def\s+\w+\s*\(")
DOLLAR_ENV_RE = re.compile(r'"\$[A-Za-z_][A-Za-z0-9_]*')
REMOTE_INCLUDE_RE = re.compile(r"includeConfig\s+['\"]https?://")
BARE_TEMPDIR_RE = re.compile(r"=\s*tempDir\b")


def split_tempdir_java_block(lines, start):
    """
    A helper to fix the java.nio error. Count all the line including in the function /
    expression def (), look for everything inside the parenthesis. it counts parentheses
    even in strings or comments. Such edit can actually screwup the parser because of
    unbalanced parenthesis as per the new parser.
    """
    balance = lines[start].count("(") - lines[start].count(")")
    i = start + 1
    while balance > 0 and i < len(lines):
        balance += lines[i].count("(") - lines[i].count(")")
        i += 1
    return i


def check_text(text):
    """
    Search configuration text for patterns that need review, without editing it.

    Return a list of (line_number, code, message) tuples. Line numbers start
    at 1; each code identifies the issue and each message describes it.
    These text searches can also match content in comments or strings.
    (TODO: maybe avoid checking the comment but anyway not important here)
    """
    findings = []
    lines = text.splitlines()
    for n, line in enumerate(lines, start=1):
        if DEF_RE.match(line):
            # This one is to catch the java.io error and the parsing error of parenthesis
            findings.append((n, "DEF_IN_CONFIG", "method definition inside *.config"))
        for m in DOLLAR_ENV_RE.finditer(line):
            findings.append(
                (
                    n,
                    "DOLLAR_ENV",
                    f"raw env var {m.group(0)} -> use \"${{env('...')}}\"",
                )
            )
        if REMOTE_INCLUDE_RE.search(line):
            findings.append((n, "REMOTE_INCLUDE", "remote includeConfig URL"))
    for m in BARE_TEMPDIR_RE.finditer(text):
        line_no = text.count("\n", 0, m.start()) + 1
        def_line = text.splitlines()[line_no - 1].lstrip()
        if def_line.startswith("tempDir"):
            continue
        findings.append((line_no, "BARE_TEMPDIR", "use of `tempDir` -> `= 'auto'`"))
    return findings


def fix_text(text):
    """
    Replace detected Java temporary-directory assignments and tempDir uses.
    """
    applied = []
    lines = text.splitlines(keepends=True)
    out = []
    i = 0
    while i < len(lines):
        stripped = lines[i].lstrip()
        if (
            stripped.startswith("tempDir")
            and "=" in lines[i]
            and "java.nio" in "".join(lines[i : i + 8])
        ):
            i = split_tempdir_java_block(lines, i)
            out.append("tempDir = 'auto'\n")
            applied.append("JAVA_NIO_TEMP")
        else:
            out.append(lines[i])
            i += 1
    new_text = "".join(out)
    if BARE_TEMPDIR_RE.search(new_text):
        # Preserve lines beginning with tempDir; on other lines, replace
        # tempDir when it appears as the assigned value.
        fixed_lines = []
        for line in new_text.splitlines(keepends=True):
            if line.lstrip().startswith("tempDir"):
                fixed_lines.append(line)
            else:
                fixed_lines.append(BARE_TEMPDIR_RE.sub("= 'auto'", line))
        newer_text = "".join(fixed_lines)
        if newer_text != new_text:
            applied.append("BARE_TEMPDIR")
            new_text = newer_text
    return new_text, applied


def main(argv):
    """
    Check files in the directories named by the command-line arguments.

    `argv` includes the script name first. With --fix, write changed files
    and save their previous contents in backup files. Print each issue and
    a summary. Return 1 if issues remain or files could not be read, else 0.
    """
    do_fix = "--fix" in argv
    dirs = [dir for dir in argv[1:] if dir != "--fix"]
    if not dirs:
        dirs = [".", str(Path.home() / ".nextflow" / "assets")]

    files = []
    for dir in dirs:
        root = Path(dir)
        if not root.exists():
            print(f"skip missing dir: {dir}")
            continue
        files.extend(sorted(root.rglob("*.config")))

    total_findings = 0
    total_fixed = 0
    for path in files:
        try:
            original_text = path.read_text()
        except (OSError, UnicodeDecodeError) as exc:
            print(f"{path}: unreadable ({exc})")
            total_findings += 1
            continue

        text_to_check = original_text
        if do_fix:
            patched_text, applied = fix_text(original_text)
            if patched_text != original_text:
                path.with_name(path.name + ".bak").write_text(original_text)
                path.write_text(patched_text)
                total_fixed += 1
                print(
                    f"{path}: auto-fixed {sorted(set(applied))} "
                    f"(backup: {path.name}.bak)"
                )
                text_to_check = patched_text
        for line_no, code, msg in check_text(text_to_check):
            print(f"{path}:{line_no}: [{code}] {msg}")
            total_findings += 1

    print(
        f"--- scanned {len(files)} config file(s), "
        f"{total_fixed} auto-fixed, {total_findings} finding(s) left ---"
    )
    return 1 if total_findings else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
