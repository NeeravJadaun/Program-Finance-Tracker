# Power Query example

`import_expenses.pq` is a Power Query (M) script that imports `sample_expenses.csv`, converts
types, and labels rows that fail validation. It is a standalone example. This repository
has no Power BI file and no Excel workbook that contains the query.

## What it checks

| Check | Result when it fails |
|---|---|
| Required columns `txn_id`, `txn_date`, `program_id`, `vendor_id`, `amount_cad` exist | The query stops with a "Missing columns" error that lists them |
| Required fields are not blank | `Missing <field>` in `validation_issues` |
| `txn_date` is a real `yyyy-MM-dd` date | `Invalid date (expected yyyy-MM-dd)` |
| `amount_cad` is numeric | `Amount is not a number` |

Rows that fail stay in the output with `is_valid = FALSE`. They are not dropped or fixed.
The sample CSV has 12 clean synthetic expenses and two rows with deliberate problems:
`TXN-9001` has the impossible date 2026-09-31, and `TXN-9002` has no program and the amount `n/a`.

## Use it in Excel

1. Copy `sample_expenses.csv` somewhere on your machine.
2. In Excel, go to **Data > Get Data > From Other Sources > Blank Query**, then open the **Advanced Editor**.
3. Paste the contents of `import_expenses.pq`.
4. Change `FilePath` on the first line of the `let` block to the full path of the CSV.
5. Click **Done**, check the preview, then **Close & Load**.
6. To review problems, filter `is_valid` to `FALSE`.

Power BI Desktop works the same way: **Get Data > Blank Query > Advanced Editor**.

## Status

I wrote the script against the Power Query M language reference. It has not been run in this
repository, because neither Excel nor Power BI runs in this environment. Test it on the sample
CSV before using it on other data.
