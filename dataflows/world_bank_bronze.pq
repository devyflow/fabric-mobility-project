// Dataflow Gen2 query. Configure a Lakehouse destination; this file alone does not deploy it.
// Values below are development defaults. Replace with pipeline parameters in Fabric.
let
    Country = "USA",
    StartYear = 2024,
    EndYear = 2025,
    RunId = "manual-development",
    ExtractedAt = DateTimeZone.RemoveZone(DateTimeZone.FixedUtcNow()),
    FetchPage = (Page as number) as record =>
        let
            Response = Binary.Buffer(Web.Contents("https://api.worldbank.org", [
                RelativePath = "v2/country/" & Country & "/indicator/NY.GDP.MKTP.CD",
                Query = [format="json", date=Text.From(StartYear) & ":" & Text.From(EndYear), per_page="1000", page=Text.From(Page)],
                Timeout = #duration(0,0,2,0)
            ])),
            Parsed = Json.Document(Response)
        in [page=Page, pages=Number.From(Parsed{0}[pages]), payload_json=Text.FromBinary(Response, TextEncoding.Utf8)],
    First = FetchPage(1),
    Pages = if First[pages] < 1 or First[pages] > 100 then error "Unexpected page count" else
        List.Generate(() => First, each [page] <= First[pages],
            each if [page] < First[pages] then FetchPage([page]+1) else [page=First[pages]+1]),
    Rows = Table.FromRecords(Pages),
    WithSource = Table.AddColumn(Rows, "source", each "world_bank_gdp", type text),
    WithCountry = Table.AddColumn(WithSource, "country_code", each Country, type text),
    WithRun = Table.AddColumn(WithCountry, "run_id", each RunId, type text),
    WithTime = Table.AddColumn(WithRun, "ingested_at_utc", each ExtractedAt, type datetime),
    Typed = Table.TransformColumnTypes(WithTime, {{"page", Int64.Type}, {"pages", Int64.Type}, {"payload_json", type text}})
in
    Typed
