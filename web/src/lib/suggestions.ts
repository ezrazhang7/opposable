export const CATEGORIES = ["Research", "Code", "Data", "Files"] as const;
export type Category = (typeof CATEGORIES)[number];

/** A chip shows the short label; submitting sends the full task. Each one is
 *  something the sandbox can actually finish with shell, files and web_fetch. */
export type Suggestion = { label: string; task: string };

export const SUGGESTIONS: Record<Category, Suggestion[]> = {
  Research: [
    {
      label: "Compare vector databases",
      task: "Compare the three most-cited open-source vector databases and write a recommendation with sources.",
    },
    {
      label: "Summarise a release note",
      task: "Read the Python 3.13 release notes and summarise what breaks for library authors.",
    },
    {
      label: "Deep-space probe briefing",
      task: "Collect the launch dates and status of every active deep-space probe into a briefing.",
    },
    {
      label: "SSE vs WebSockets",
      task: "Find out how SSE differs from WebSockets and write a one-page decision note.",
    },
    {
      label: "Read the ReAct paper",
      task: "Summarise the argument of the ReAct paper and note what it does not solve.",
    },
    {
      label: "Tabulate OSS licences",
      task: "Survey the licence terms of five open-source agent frameworks and tabulate them.",
    },
  ],
  Code: [
    {
      label: "FastAPI todo service",
      task: "Build a FastAPI todo service with SQLite, write pytest tests, and run them.",
    },
    {
      label: "CSV to markdown CLI",
      task: "Write a CLI that renders a markdown table from a CSV file, with tests.",
    },
    {
      label: "Profile and optimise",
      task: "Profile a naive fibonacci implementation, optimise it, and prove the speedup.",
    },
    {
      label: "Rate limiter with tests",
      task: "Implement a rate limiter in Python with unit tests covering the burst case.",
    },
    {
      label: "Validate JSON files",
      task: "Write a script that checks a directory of JSON files against a schema.",
    },
    {
      label: "Port a shell script",
      task: "Port a small shell script to Python and verify the output is identical.",
    },
  ],
  Data: [
    {
      label: "Chart a sales trend",
      task: "Generate a synthetic sales CSV, clean it, and chart the monthly trend as SVG.",
    },
    {
      label: "Summarise a log file",
      task: "Parse a log file into a summary table of error counts by hour.",
    },
    {
      label: "Describe a dataset",
      task: "Compute summary statistics for a CSV and write the findings to a report.",
    },
    {
      label: "Deduplicate a list",
      task: "Deduplicate a messy contact list and explain every merge decision.",
    },
    { label: "Flatten JSON to CSV", task: "Convert a nested JSON dump into a flat CSV with a documented schema." },
    {
      label: "Find outliers",
      task: "Detect outliers in a numeric column and write up what you found.",
    },
  ],
  Files: [
    {
      label: "Organise a folder",
      task: "Organise the files in the sandbox into a dated structure and write an index.",
    },
    { label: "Collect every TODO", task: "Find every TODO comment in a project tree and collect them into todo.md." },
    { label: "Write a README", task: "Write a README for a directory by reading the code it contains." },
    {
      label: "Split a long document",
      task: "Split a long markdown document into per-section files with a table of contents.",
    },
    { label: "Find duplicate images", task: "Check a folder of images for duplicates by hash and report them." },
    { label: "Build a file manifest", task: "Build a manifest of every file with size and modified date as CSV." },
  ],
};
