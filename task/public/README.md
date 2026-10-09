# Starter materials

Implement an executable program named `q` at the solution root (the
directory containing `package.json`), per `task/instruction.md`.

- The file `task/public/q` in this directory is a stub. Your implementation
  MUST replace it: the verifier runs `$SOLUTION_DIR/q ...` with
  `$QDATA_DIR` pointing at a fresh state directory.
- `q` MUST be executable (`chmod +x q`) and MUST run with
  `#!/usr/bin/env python3` using only the Python 3 standard library.
- Do not print anything to stdout except what the instruction specifies;
  diagnostics go to stderr.
- You do not need networking, a daemon, or any background process: `q` is a
  short-lived CLI; every command opens the state dir, does its work, and
  exits.
