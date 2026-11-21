"""Render bounded date-fns PR jobs; credentials stay in the no-application fetch job."""

import argparse
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

FETCH = """  fetch-map:
    runs-on: ubuntu-24.04
    timeout-minutes: 5
    permissions:
      contents: read
      actions: read
    outputs:
      sha256: ${{ steps.fetch.outputs.sha256 }}
    steps:
      - uses: actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5
        with:
          repository: SharmaKunal14/smart-ci
          ref: TOOL_COMMIT
          path: control
          persist-credentials: false
      - name: Authenticate producer and download exact base map
        id: fetch
        continue-on-error: true
        env:
          GH_TOKEN: ${{ github.token }}
          BASE_SHA: ${{ github.event.pull_request.base.sha }}
          BASE_BRANCH: ${{ github.event.pull_request.base.ref }}
        run: |
          python3 control/scripts/fetch_typescript_map.py \\
            --repository SharmaKunal14/date-fns --commit "$BASE_SHA" --branch "$BASE_BRANCH" \\
            --workflow .github/workflows/smartci-precompute.yml \\
            --publisher-template control/examples/date-fns/precompute.yml.in \\
            --tool-repository SharmaKunal14/smart-ci --tool-ref TOOL_COMMIT \\
            --output "$RUNNER_TEMP/base-map.json" > "$RUNNER_TEMP/receipt.json"
          python3 - <<'PYTHON'
          import json, os
          from pathlib import Path
          receipt = json.loads((Path(os.environ['RUNNER_TEMP']) / 'receipt.json').read_text())
          with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
              output.write('sha256=' + receipt['sha256'] + '\\n')
          PYTHON
      - uses: actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02
        if: steps.fetch.outcome == 'success'
        with:
          name: verified-base-map-${{ github.run_id }}-${{ github.run_attempt }}
          path: |
            ${{ runner.temp }}/base-map.json
            ${{ runner.temp }}/receipt.json
          retention-days: 3
          if-no-files-found: error
"""

DOWNLOAD = """      - name: Download authenticated map
        continue-on-error: true
        uses: actions/download-artifact@d3f86a106a0bac45b974a628896c90dbdf5c8093
        with:
          name: verified-base-map-${{ github.run_id }}-${{ github.run_attempt }}
          path: ${{ runner.temp }}/verified-map
"""


def render(commit: str) -> str:
    if re.fullmatch("[a-f0-9]{40}", commit) is None:
        raise ValueError("immutable tool commit required")
    # Reuse the already-reviewed command and failure-retention flow. Fail if its
    # structure drifts instead of silently generating a different experiment.
    source = (ROOT / "examples/date-fns/optimized-timing.yml").read_text()
    header, job = source.split("jobs:\n", 1)
    header = header.replace(
        "Smart CI / optimized date-fns PR comparison",
        "Smart CI / precomputed map PR comparison",
    )
    header = header.replace(
        "    types:",
        "    branches: [codex/smartci-precomputed-base, codex/smartci-precomputed-fix]\n    types:",
    )
    job = job.replace("  timing:\n", "  baseline:\n", 1)
    strategy = job.split("    strategy:\n", 1)[1].split("    name:", 1)[0]
    job = job.replace(
        strategy,
        """      fail-fast: false
      max-parallel: 2
      matrix:
        variant: [native, rebuild]
""",
    )
    job = job.replace("ref: ${{ matrix.tool_ref }}", "ref: " + commit)
    start = job.index(
        "        env:\n          VARIANT:", job.index("- name: Install pinned Smart CI")
    )
    end = job.index("      - name: Run measured test command", start)
    job = job[:start] + "        run: uv sync --frozen --no-dev\n" + job[end:]
    cached = job.replace("  baseline:\n", "  cached:\n    needs: fetch-map\n", 1)
    begin = cached.index("    strategy:\n")
    end = cached.index("    name:", begin)
    cached = cached[:begin] + cached[end:]
    cached = cached.replace(
        "if: github.repository == 'SharmaKunal14/date-fns'",
        "if: always() && !cancelled() && github.repository == 'SharmaKunal14/date-fns'",
        1,
    )
    cached = cached.replace("${{ matrix.variant != 'native' }}", "true")
    cached = cached.replace("matrix.variant != 'native'", "true")
    cached = cached.replace("${{ matrix.variant == 'native' && 1 || 0 }}", "0")
    cached = cached.replace("${{ matrix.variant }}", "cached")
    cached = cached.replace("        if: true\n", "")
    cached = cached.replace("        if: true && ", "        if: ")
    cached = cached.replace("    steps:\n", "    steps:\n" + DOWNLOAD, 1)
    cached = cached.replace(
        "          TOOL_READY:",
        "          MAP_DIGEST: ${{ needs.fetch-map.outputs.sha256 }}\n          TOOL_READY:",
    )
    marker = "              try:\n                  status = subprocess.run(command,"
    assert cached.count(marker) == 1
    cached = cached.replace(
        marker,
        """              command += ['--base-map', str(temporary / 'verified-map/base-map.json'),
                          '--base-map-sha256', os.environ['MAP_DIGEST']]
"""
        + marker,
    )
    cached = cached.replace(
        "            ${{ runner.temp }}/command-time.json",
        "            ${{ runner.temp }}/verified-map/receipt.json\n            ${{ runner.temp }}/command-time.json",
    )
    return header + "jobs:\n" + FETCH.replace("TOOL_COMMIT", commit) + job + cached


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tool-ref", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with args.output.open("x") as output:
        output.write(render(args.tool_ref))


if __name__ == "__main__":
    main()
