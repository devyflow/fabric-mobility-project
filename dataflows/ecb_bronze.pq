// Preserve CSV response text in Bronze; parse and validate in the Silver notebook.
// This query has no credentials. Use an Anonymous Web API connection.
let
    StartDate = "2025-05-25",
    EndDate = "2025-06-30",
    RunId = "manual-development",
    Response = Binary.Buffer(Web.Contents("https://data-api.ecb.europa.eu", [
        RelativePath = "service/data/EXR/D.USD.EUR.SP00.A",
        Query = [format="csvdata", startPeriod=StartDate, endPeriod=EndDate],
        Headers = [Accept="text/csv"],
        Timeout = #duration(0,0,2,0)
    ])),
    Result = #table(
        type table [source=text, series_key=text, period_start=text, period_end=text, payload_csv=text, run_id=text, ingested_at_utc=datetime],
        {{"ecb_fx", "D.USD.EUR.SP00.A", StartDate, EndDate, Text.FromBinary(Response, TextEncoding.Utf8), RunId, DateTimeZone.RemoveZone(DateTimeZone.FixedUtcNow())}}
    )
in
    Result
