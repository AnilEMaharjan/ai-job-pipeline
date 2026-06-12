"""
Resume and cover letter PDF generation using Jake's Resume LaTeX template.
https://github.com/jakegut/resume
"""

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any


# Prefer pdflatex on PATH; fall back to the macOS TinyTeX install location.
PDFLATEX = shutil.which("pdflatex") or str(
    Path.home() / "Library/TinyTeX/bin/universal-darwin/pdflatex"
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def applicant_last_name(resume_json: dict[str, Any]) -> str:
    parts = (resume_json.get("name") or "Applicant").strip().split()
    return parts[-1] if parts else "Applicant"


def resume_pdf_name(resume_json: dict[str, Any]) -> str:
    return f"{applicant_last_name(resume_json)}_Resume.pdf"


def cover_pdf_name(resume_json: dict[str, Any]) -> str:
    return f"{applicant_last_name(resume_json)}_CoverLetter.pdf"

def _fmt_date(d: str) -> str:
    if not d or d == "Present":
        return "Present"
    try:
        from datetime import datetime
        return datetime.strptime(d, "%Y-%m").strftime("%B %Y")
    except Exception:
        return d


def _tex(s: str) -> str:
    """Escape special LaTeX characters."""
    replacements = [
        ("\\", "\\textbackslash{}"),
        ("&",  "\\&"),
        ("%",  "\\%"),
        ("$",  "\\$"),
        ("#",  "\\#"),
        ("_",  "\\_"),
        ("{",  "\\{"),
        ("}",  "\\}"),
        ("~",  "\\textasciitilde{}"),
        ("^",  "\\textasciicircum{}"),
    ]
    for char, replacement in replacements:
        s = s.replace(char, replacement)
    return s


def _skill_label(key: str) -> str:
    labels = {
        "languages_and_development": "Languages \\& Development",
        "orchestration_and_etl":     "Orchestration \\& ETL",
        "data_warehouses":           "Data Warehouses",
        "visualization":             "Visualization",
        "gtm_and_product":           "GTM \\& Product",
    }
    return labels.get(key, key.replace("_", " ").title())


# ── Jake's Resume LaTeX template ──────────────────────────────────────────────

PREAMBLE = r"""
\documentclass[letterpaper,11pt]{article}

\usepackage{latexsym}
\usepackage[top=0.5in, bottom=0.5in, left=0.6in, right=0.6in, headsep=0pt, footskip=0pt]{geometry}
\usepackage{needspace}
\usepackage{titlesec}
\usepackage{marvosym}
\usepackage[usenames,dvipsnames]{color}
\usepackage{verbatim}
\usepackage{enumitem}
\usepackage[hidelinks]{hyperref}
\usepackage{fancyhdr}
\usepackage[english]{babel}
\usepackage{tabularx}
\usepackage[T1]{fontenc}
\usepackage[sfdefault]{roboto}
\input{glyphtounicode}

\pagestyle{fancy}
\fancyhf{}
\fancyfoot{}
\renewcommand{\headrulewidth}{0pt}
\renewcommand{\footrulewidth}{0pt}

\linespread{1.05}
\urlstyle{same}
\raggedbottom
\raggedright
\setlength{\tabcolsep}{0in}

\titleformat{\section}{
  \vspace{-4pt}\bfseries\raggedright\normalsize
}{}{0em}{}[\color{black}\titlerule \vspace{-5pt}]

\pdfgentounicode=1

%--- Custom commands ---

\newcommand{\resumeItem}[1]{
  \item\small{
    {#1 \vspace{-2pt}}
  }
}

\newcommand{\resumeSubheading}[4]{
  \vspace{-2pt}\item
    \begin{tabular*}{0.97\textwidth}[t]{l@{\extracolsep{\fill}}r}
      \textbf{#1} & #2 \\
      \textit{\small#3} & \textit{\small #4} \\
    \end{tabular*}\vspace{-7pt}
}

\newcommand{\resumeSubSubheading}[2]{
    \item
    \begin{tabular*}{0.97\textwidth}{l@{\extracolsep{\fill}}r}
      \textit{\small#1} & \textit{\small #2} \\
    \end{tabular*}\vspace{-7pt}
}

\newcommand{\resumeProjectHeading}[2]{
    \item
    \begin{tabular*}{0.97\textwidth}{l@{\extracolsep{\fill}}r}
      \small#1 & #2 \\
    \end{tabular*}\vspace{-7pt}
}

\newcommand{\resumeSubItem}[1]{\resumeItem{#1}\vspace{-4pt}}
\renewcommand\labelitemii{$\vcenter{\hbox{\tiny$\bullet$}}$}
\newcommand{\resumeSubHeadingListStart}{\begin{itemize}[leftmargin=0.15in, label={}]}
\newcommand{\resumeSubHeadingListEnd}{\end{itemize}}
\newcommand{\resumeItemListStart}{\begin{itemize}}
\newcommand{\resumeItemListEnd}{\end{itemize}\vspace{-5pt}}

\begin{document}
"""


def _build_resume_tex(resume: dict[str, Any]) -> str:
    name     = _tex(resume.get("name", ""))
    email    = resume.get("email", "")
    phone    = _tex(resume.get("phone", ""))
    loc      = _tex(resume.get("location", ""))
    li_url   = resume.get("linkedin", "")
    li_label = _tex(li_url.replace("https://", "").rstrip("/"))
    summary  = _tex(resume.get("summary", ""))

    # ── Header ────────────────────────────────────────────────────────────────
    header = f"""
\\begin{{center}}
    \\textbf{{\\Huge \\scshape {name}}} \\\\ \\vspace{{1pt}}
    \\small {phone} $|$
    \\href{{mailto:{email}}}{{\\underline{{{_tex(email)}}}}} $|$
    {_tex(loc)} $|$
    \\href{{{li_url}}}{{\\underline{{{li_label}}}}}
\\end{{center}}
"""

    # ── Summary ───────────────────────────────────────────────────────────────
    summary_section = f"""
\\section{{Summary}}
 \\begin{{itemize}}[leftmargin=0.15in, label={{}}]
    \\small{{\\item{{{summary}}}}}
 \\end{{itemize}}
"""

    # ── Skills ────────────────────────────────────────────────────────────────
    skills_rows = ""
    for key, items in resume.get("skills", {}).items():
        label = _skill_label(key)
        value = _tex(", ".join(items))
        skills_rows += f"    \\textbf{{{label}}}{{: {value}}} \\\\\n"

    skills_section = f"""
\\section{{Skills}}
 \\begin{{itemize}}[leftmargin=0.15in, label={{}}]
    \\small{{\\item{{
{skills_rows}
    }}}}
 \\end{{itemize}}
"""

    # ── Experience ────────────────────────────────────────────────────────────
    exp_items = ""
    for exp in resume.get("experience", []):
        company    = _tex(exp.get("company", ""))
        sector     = _tex(exp.get("sector", ""))
        title      = _tex(exp.get("title", ""))
        location   = _tex(exp.get("location", ""))
        start      = _tex(_fmt_date(exp.get("start_date", "")))
        end        = _tex(_fmt_date(exp.get("end_date", "Present")))
        topline    = _tex(exp.get("description", ""))
        platforms  = exp.get("platforms", [])
        key_models = exp.get("key_models", "")
        bullets    = exp.get("bullets", [])

        company_label = f"{company} {{\\small\\normalfont\\textit{{({sector})}}}}" if sector else company
        date_range    = f"{start}--{end}"

        bullet_items = ""

        # Only show Platforms/Key Models for roles with substantial tech content
        if platforms:
            bullet_items += f"    \\resumeItem{{\\textbf{{Platforms Used:}} {_tex(', '.join(platforms))}}}\n"
        if key_models:
            bullet_items += f"    \\resumeItem{{\\textbf{{Key Models Created:}} {_tex(key_models)}}}\n"
        for bullet in bullets:
            bullet_items += f"    \\resumeItem{{{_tex(bullet)}}}\n"

        exp_items += f"""
  \\needspace{{5\\baselineskip}}
  \\resumeSubheading
    {{{company_label}}}{{{location}}}
    {{{title}}}{{{date_range}}}
  \\resumeItemListStart
{bullet_items}  \\resumeItemListEnd
"""

    exp_section = f"""
\\section{{Experience}}
  \\resumeSubHeadingListStart
{exp_items}
  \\resumeSubHeadingListEnd
"""

    # ── Education & Certs ─────────────────────────────────────────────────────
    edu_items = ""
    for edu in resume.get("education", []):
        institution = _tex(edu.get("institution", ""))
        degree      = _tex(edu.get("degree", ""))
        year        = _tex(str(edu.get("graduation_year", "")))
        edu_items += f"""
  \\resumeSubheading
    {{{institution}}}{{}}
    {{{degree}}}{{Class of {year}}}
"""

    certs = resume.get("certifications", [])
    cert_line = " $|$ ".join("\\small " + _tex(c) for c in certs)

    edu_section = f"""
\\section{{Education, Personal and Professional Certification}}
  \\resumeSubHeadingListStart
{edu_items}
  \\resumeSubHeadingListEnd
  \\vspace{{2pt}}
  \\small {cert_line}
"""

    return PREAMBLE + header + summary_section + skills_section + exp_section + edu_section + "\n\\end{document}\n"


# ── Cover letter ──────────────────────────────────────────────────────────────

def _build_cover_letter_tex(text: str, resume: dict[str, Any]) -> str:
    name   = _tex(resume.get("name", ""))
    email  = resume.get("email", "")
    phone  = _tex(resume.get("phone", ""))
    loc    = _tex(resume.get("location", ""))
    li_url = resume.get("linkedin", "")

    # Strip any AI preamble ("Here is the cover letter:", "---" separators)
    lines = text.split("\n")
    cleaned_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped.lower().startswith("here is") and "cover letter" in stripped.lower():
            continue
        if stripped in ("---", "—", "–"):
            continue
        cleaned_lines.append(line)
    text = "\n".join(cleaned_lines).strip()

    # Strip trailing signature (— Name or just Name on its own at the end)
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    if paragraphs:
        last = paragraphs[-1]
        if last.startswith("—") or last.startswith("-") or last == resume.get("name", ""):
            paragraphs = paragraphs[:-1]

    body = "\n\n".join(_tex(p.replace("\n", " ")) for p in paragraphs)

    return f"""\\documentclass[letterpaper,11pt]{{article}}
\\usepackage[hidelinks]{{hyperref}}
\\usepackage[margin=1in]{{geometry}}
\\usepackage{{parskip}}
\\usepackage{{fontenc}}
\\pagestyle{{empty}}

\\begin{{document}}

{{\\large \\textbf{{{name}}}}}\\\\
{_tex(email)} $|$ {phone} $|$ {loc} $|$ \\href{{{li_url}}}{{{_tex(li_url.replace('https://',''))}}}

\\noindent\\rule{{\\textwidth}}{{0.4pt}}
\\vspace{{6pt}}

{body}

\\vspace{{16pt}}
\\noindent\\textbf{{{name}}}

\\end{{document}}
"""


# ── Compile ───────────────────────────────────────────────────────────────────

def _compile_tex(tex: str, output_pdf: Path) -> Path:
    """Write .tex to a temp dir, compile twice (for references), move PDF out."""
    output_pdf.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmpdir:
        tex_file = Path(tmpdir) / "doc.tex"
        tex_file.write_text(tex, encoding="utf-8")

        for _ in range(2):  # two passes for stable output
            result = subprocess.run(
                [PDFLATEX, "-interaction=nonstopmode", "-output-directory", tmpdir, str(tex_file)],
                capture_output=True, text=True
            )

        pdf_out = Path(tmpdir) / "doc.pdf"
        if not pdf_out.exists():
            # Print log for debugging
            log = Path(tmpdir) / "doc.log"
            raise RuntimeError(f"pdflatex failed:\n{log.read_text()[-2000:] if log.exists() else result.stderr}")

        import shutil
        shutil.copy2(str(pdf_out), str(output_pdf))

    return output_pdf


# ── Public API ────────────────────────────────────────────────────────────────

def write_resume_pdf(resume_json: dict[str, Any], output_path: str | Path) -> Path:
    output_path = Path(output_path)
    tex = _build_resume_tex(resume_json)
    # Also save the .tex for inspection
    output_path.with_suffix(".tex").write_text(tex, encoding="utf-8")
    return _compile_tex(tex, output_path)


def write_cover_letter_pdf(
    text: str,
    applicant_name: str,
    output_path: str | Path,
    resume_json: dict[str, Any] | None = None,
) -> Path:
    output_path = Path(output_path)
    resume = resume_json or {"name": applicant_name}
    tex = _build_cover_letter_tex(text, resume)
    output_path.with_suffix(".tex").write_text(tex, encoding="utf-8")
    return _compile_tex(tex, output_path)
