"""Export completed benchmark evidence without sending source data off-host."""

import base64
import csv
from html import escape
from io import StringIO
import json
import textwrap

import pymupdf

from app.services.storage import storage

FORMATS = {
    "json": "application/json", "csv": "text/csv",
    "html": "text/html", "pdf": "application/pdf",
}
CSV_METRICS = ("cer", "wer", "text_accuracy", "ocr_accuracy", "layout_similarity", "page_completeness",
               "tables_score", "images_score", "docx_valid", "cpu_seconds", "peak_rss_mib",
               "temp_storage_peak_bytes", "parse_seconds", "ocr_seconds", "docx_seconds")


def _value(value) -> str:
    return "Unavailable" if value is None else str(value)


def _overview(run: dict) -> list[tuple[str, str]]:
    summary = run["summary"]
    fields = [
        ("Benchmark ID", run["id"]),
        ("Application version", run["application_version"]),
        ("Dataset version", run["dataset_version"]),
        ("Dataset SHA-256", run["dataset_sha256"]),
        ("Executed at (UTC)", run["created_at"]),
        ("Documents tested", str(run["total"])),
        ("Successful conversions", str(summary["successful_conversions"])),
        ("Failed conversions", str(summary["failed_conversions"])),
        ("Overall score", _value(summary["overall_score"])),
        ("Measured scoring weight", str(summary["coverage_weight"])),
        ("Passed targets", str(summary["passed"])),
        ("Median / p95 / p99 (seconds)", " / ".join(_value(summary[key]) for key in ("median_seconds", "p95_seconds", "p99_seconds"))),
        ("Failed case IDs", ", ".join(summary["failed_ids"]) or "None"),
    ]
    for key in CSV_METRICS:
        if key in summary["metrics"]:
            value = summary["metrics"][key]
            fields.append((key.replace("_", " ").capitalize(), f"{value:.4g}"))
    if summary.get("baseline"):
        fields.append(("Comparable baseline", str(summary["baseline"]["run_id"])))
        fields.append(("Change in score", _value(summary["baseline"]["delta"])))
    fields.append(("Manual references compared", str(summary["references_compared"])))
    return fields


def _pictures(results: list[dict]):
    remaining = 4
    ordered = sorted(results, key=lambda row: (row["passed"] is not False, row["case_id"]))
    for row in ordered:
        keys = row.pop("_image_keys", {})
        source = keys.get("original_001")
        output = keys.get("rendered_001")
        if remaining <= 0 or not (source and output):
            continue
        try:
            with storage().open(source) as left, storage().open(output) as right:
                images = (left.read(1_500_001), right.read(1_500_001))
        except (OSError, RuntimeError):
            continue
        if all(0 < len(image) <= 1_500_000 for image in images):
            yield row["case_id"], *images
            remaining -= 1


def _csv(results: list[dict]) -> bytes:
    buffer = StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["case_id", "category", "status", "passed", "score", "duration_seconds", *CSV_METRICS, "error"])
    for row in results:
        values = [row.get("case_id"), row.get("category"), row.get("status"), row.get("passed"), row.get("score"),
                  row.get("duration_seconds"), *((row.get("metrics") or {}).get(key) for key in CSV_METRICS), row.get("error")]
        writer.writerow(["'" + value if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")) else value
                         for value in values])
    return buffer.getvalue().encode("utf-8")


def _html(run: dict, results: list[dict], pictures) -> bytes:
    def items(pairs):
        return "".join(f"<dt>{escape(str(key))}</dt><dd>{escape(str(value))}</dd>" for key, value in pairs)

    summary = run["summary"]
    rows = "".join(
        "<tr>" + "".join(f"<td>{escape(_value(value))}</td>" for value in (
            row["case_id"], row["category"], row["status"], row["passed"], row["score"],
            row["duration_seconds"], row["error"],
        )) + "</tr>" for row in results
    )
    audit = "".join(f"<li>{escape(check['name'])} · {'Pass' if check['passed'] else 'Fail'} · {escape(check['detail'])}</li>"
                    for check in summary["security"])
    findings = "".join(
        f"<h3>{escape(row['case_id'])}</h3><ul>" + "".join(f"<li>{escape(finding)}</li>" for finding in (
            row["details"].get("critical", []) + row["details"].get("failed_targets", []) + row["details"].get("warnings", [])
        )) + "</ul>" for row in results if row.get("details") and row["passed"] is False
    )
    visual = ""
    for case_id, left, right in pictures:
        images = "".join(
            f'<figure><img alt="{label}" src="data:image/png;base64,{base64.b64encode(image).decode()}"><figcaption>{label}</figcaption></figure>'
            for label, image in (("Original", left), ("Converted", right))
        )
        visual += f'<section><h3>{escape(case_id)}</h3><div class="images">{images}</div></section>'
    recommendations = "".join(f"<li>{escape(text)}</li>" for text in summary["recommendations"])
    weights = [(name.replace("_", " ").capitalize(), _value(value)) for name, value in summary["category_scores"].items()]
    references = items(summary.get("reference_metrics", {}).items())
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; style-src 'unsafe-inline';">
<title>PDF2DOCX-BENCH report</title><style>
body{{font:16px system-ui;color:#18233a;max-width:72rem;margin:3rem auto;padding:0 1.25rem}}h1{{font-size:2rem}}
dl{{display:grid;grid-template-columns:minmax(10rem,1fr) 2fr;gap:.6rem;border:1px solid #dbe3ee;padding:1rem}}
dt{{font-weight:650}}dd{{margin:0;overflow-wrap:anywhere}}table{{width:100%;border-collapse:collapse}}
td,th{{border-bottom:1px solid #dbe3ee;text-align:left;padding:.55rem;vertical-align:top}}
.images{{display:grid;grid-template-columns:1fr 1fr;gap:1rem}}img{{width:100%;border:1px solid #dbe3ee}}
figure{{margin:0}}figcaption{{font-size:.9rem;color:#465570}}li{{margin-bottom:.4rem}}
</style></head><body><h1>PDF2DOCX-BENCH v1.0</h1><h2>{escape(run['name'])}</h2><dl>{items(_overview(run))}</dl>
<h2>Category scores</h2><dl>{items(weights)}</dl><h2>Case results</h2><table><thead><tr><th>Case</th><th>Category</th>
<th>Status</th><th>Passed</th><th>Score</th><th>Seconds</th><th>Error</th></tr></thead><tbody>{rows}</tbody></table>
<h2>Security checks</h2><ul>{audit}</ul><h2>Failure diagnostics</h2>{findings}
<h2>Visual samples</h2>{visual}<h2>Manual reference metrics</h2><dl>{references}</dl>
<h2>Recommendations</h2><ul>{recommendations}</ul></body></html>""".encode()


def _pdf(run: dict, results: list[dict], pictures) -> bytes:
    summary = run["summary"]
    lines = [run["name"], *[key + " — " + value for key, value in _overview(run)], "", "Category scores"]
    lines.extend(f"{key.replace('_', ' ').title()} — {_value(value)}" for key, value in summary["category_scores"].items())
    lines.extend(["", "Case results"])
    for row in results:
        lines.append(f"{row['case_id']}  {row['category']}  {row['status']}  Score {_value(row['score'])}  {_value(row['duration_seconds'])} s")
        if row["passed"] is False:
            for reason in (row.get("details", {}).get("critical", []) + row.get("details", {}).get("failed_targets", []))[:5]:
                lines.append(f"  {reason}")
    lines.extend(["", "Security checks", *[f"{check['name']} — {'Pass' if check['passed'] else 'Fail'}"
                                         for check in summary["security"]], "", "Recommendations", *summary["recommendations"]])
    if summary.get("reference_metrics"):
        lines += ["", "Manual reference metrics", *[f"{key}: {value:.4g}" for key, value in summary["reference_metrics"].items()]]
    lines = [piece for line in lines for piece in (textwrap.wrap(line, 91) or [""])]
    with pymupdf.open() as document:
        for offset in range(0, len(lines), 48):
            page = document.new_page(width=595, height=842)
            page.insert_text((48, 60), "PDF2DOCX-BENCH v1.0", fontsize=21, fontname="hebo", color=(.09, .17, .33))
            for index, line in enumerate(lines[offset:offset + 48]):
                safe_line = line.encode("cp1252", errors="replace").decode("cp1252")
                page.insert_text((48, 95 + index * 14), safe_line, fontsize=9.5)
        for case_id, left, right in pictures:
            page = document.new_page(width=842, height=595)
            page.insert_text((36, 42), f"{case_id} · Visual comparison", fontsize=18, fontname="hebo")
            for index, image in enumerate((left, right)):
                x = 36 + index * 399
                page.insert_text((x, 72), ("Original", "Converted")[index], fontsize=12)
                page.insert_image(pymupdf.Rect(x, 90, x + 371, 560), stream=image)
        return document.tobytes(garbage=4, deflate=True)


def export_report(format: str, run: dict, results: list[dict]) -> bytes:
    pictures = list(_pictures(results)) if format in {"html", "pdf"} else []
    for row in results:
        row.pop("_image_keys", None)
    if format == "json":
        return json.dumps({"run": run, "results": results}, ensure_ascii=False, indent=2).encode()
    if format == "csv":
        return _csv(results)
    if format == "html":
        return _html(run, results, pictures)
    return _pdf(run, results, pictures)
