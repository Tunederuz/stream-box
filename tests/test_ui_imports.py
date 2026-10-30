"""ui.py (the Qt app) is started directly, with only app/player on its import path: neither it nor the modules it
imports may pull in sysparts.py, whose system modules (app/system) it can't find. It crashed on the box that way,
and the player fell back to mpv alone."""
import ast, os, unittest

PLAYER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app", "player")


def local_imports(name):
    with open(os.path.join(PLAYER, name + ".py"), encoding="utf-8") as f:
        tree = ast.parse(f.read())
    found = set()
    for node in ast.walk(tree):
        names = ([a.name for a in node.names] if isinstance(node, ast.Import)
                 else [node.module] if isinstance(node, ast.ImportFrom) and node.module else [])
        found.update(n.split(".")[0] for n in names if os.path.exists(os.path.join(PLAYER, n.split(".")[0] + ".py")))
    return found


class UiImports(unittest.TestCase):
    def test_no_system_part(self):
        seen, todo = set(), ["ui"]
        while todo:
            name = todo.pop()
            if name not in seen:
                seen.add(name)
                todo.extend(local_imports(name))
        self.assertNotIn("sysparts", seen)


if __name__ == "__main__":
    unittest.main()
