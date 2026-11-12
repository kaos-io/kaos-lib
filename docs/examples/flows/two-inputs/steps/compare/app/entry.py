"""compare: the files that are in `after` and not in `before`, and the other way round."""
from kaos_lib import step


def names(folder):
    return {str(f.relative_to(folder)) for f in folder.rglob("*") if f.is_file()}


def main() -> None:
    step.start()
    before, after = names(step.input("before")), names(step.input("after"))  # two folders, two versions
    added, removed = sorted(after - before), sorted(before - after)
    lines = [f"added {name}" for name in added] + [f"removed {name}" for name in removed]
    (step.output("changes") / "changes.txt").write_text("\n".join(lines) + "\n")
    step.result(added=len(added), removed=len(removed))


if __name__ == "__main__":
    main()
