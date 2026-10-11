import os
import subprocess
import sys


def test_optional_cnsenti_tools_are_not_imported_during_service_import():
    env = {**os.environ, "PYTHONWARNINGS": "error::Warning"}

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import app.services.acceptance_criteria_service; import app.services.short_drama_lab_service",
        ],
        cwd=os.getcwd(),
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )

    assert result.returncode == 0, result.stderr
