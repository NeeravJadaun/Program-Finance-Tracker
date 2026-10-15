// Power Query (M) example: import a sample expense CSV and validate it.
// Usage: see powerquery/README.md. Change FilePath below before running.
//
// Output: one row per CSV line with typed columns plus
//   validation_issues  text listing every problem found ("" when none)
//   is_valid           true when validation_issues is empty
// Rows with problems are kept and labelled, not dropped or silently fixed.
let
    FilePath = "C:\Data\sample_expenses.csv",
    RequiredFields = {"txn_id", "txn_date", "program_id", "vendor_id", "amount_cad"},

    Source = Csv.Document(
        File.Contents(FilePath),
        [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]
    ),
    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),

    // Stop with a clear message if a required column is absent altogether.
    MissingColumns = List.Difference(RequiredFields, Table.ColumnNames(Promoted)),
    Checked =
        if List.IsEmpty(MissingColumns) then Promoted
        else error Error.Record(
            "Missing columns",
            "The CSV is missing required columns: " & Text.Combine(MissingColumns, ", ")
        ),

    // Trim every text value; Csv.Document returns text for all columns.
    Trimmed = Table.TransformColumns(Checked, {}, each if _ = null then null else Text.Trim(_)),

    // Typed copies: null when the text cannot be converted, so the problem is reported below.
    WithDate = Table.AddColumn(
        Trimmed, "txn_date_typed",
        each try Date.FromText([txn_date], [Format = "yyyy-MM-dd", Culture = "en-CA"]) otherwise null,
        type nullable date
    ),
    WithAmount = Table.AddColumn(
        WithDate, "amount_cad_typed",
        each try Currency.From(Number.FromText([amount_cad], "en-US")) otherwise null,
        Currency.Type
    ),

    MissingFieldIssues = (row as record) as list =>
        List.Transform(
            List.Select(RequiredFields, (f) => let v = Record.Field(row, f) in v = null or v = ""),
            (f) => "Missing " & f
        ),

    WithIssues = Table.AddColumn(
        WithAmount, "validation_issues",
        each Text.Combine(
            List.RemoveNulls(
                MissingFieldIssues(_) & {
                    if [txn_date] <> null and [txn_date] <> "" and [txn_date_typed] = null
                        then "Invalid date (expected yyyy-MM-dd)" else null,
                    if [amount_cad] <> null and [amount_cad] <> "" and [amount_cad_typed] = null
                        then "Amount is not a number" else null
                }
            ),
            "; "
        ),
        type text
    ),
    WithValid = Table.AddColumn(WithIssues, "is_valid", each [validation_issues] = "", type logical),

    Result = Table.RenameColumns(
        Table.RemoveColumns(WithValid, {"txn_date", "amount_cad"}),
        {{"txn_date_typed", "txn_date"}, {"amount_cad_typed", "amount_cad"}}
    ),
    TextTyped = Table.TransformColumnTypes(
        Result,
        {{"txn_id", type text}, {"program_id", type text}, {"vendor_id", type text},
         {"po_id", type text}, {"category", type text}, {"description", type text}}
    ),
    Ordered = Table.ReorderColumns(
        TextTyped,
        {"txn_id", "txn_date", "program_id", "vendor_id", "po_id", "amount_cad", "category",
         "description", "is_valid", "validation_issues"}
    )
in
    Ordered
