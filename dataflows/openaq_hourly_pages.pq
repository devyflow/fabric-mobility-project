// Name this function fxOpenAQHourlyPages. It accepts a secure request function,
// so the query and its parameters can be committed without an API key.
// RequestPage must implement (relative path as text, query as record) as binary.
// Do not deploy until a credential-backed X-API-Key request path is verified.
(RequestPage as function, SensorIds as list, FromUtc as text, ToUtc as text, RunId as text) as table =>
let
    PageSize = 1000,
    PageLimit = 100,
    ExtractedAt = DateTimeZone.RemoveZone(DateTimeZone.FixedUtcNow()),
    ForSensor = (SensorId as number) as list =>
        let
            Fetch = (Page as number) as record =>
                let
                    Payload = Binary.Buffer(RequestPage("v3/sensors/" & Text.From(SensorId) & "/hours",
                        [datetime_from=FromUtc, datetime_to=ToUtc, limit=Text.From(PageSize), page=Text.From(Page)])),
                    Parsed = Json.Document(Payload),
                    Count = List.Count(Parsed[results])
                in
                    if Number.From(Parsed[meta][page]) <> Page then error "Unexpected API page"
                    else [sensor_id=SensorId, page=Page, result_count=Count,
                        payload_json=Text.FromBinary(Payload, TextEncoding.Utf8)],
            Pages = List.Generate(() => Fetch(1), each _ <> null,
                each if [result_count] < PageSize then null
                     else if [page] >= PageLimit then error "OpenAQ pagination exceeded limit"
                     else Fetch([page] + 1))
        in
            Pages,
    Checked = if List.IsEmpty(SensorIds) or List.Count(List.Distinct(SensorIds)) <> List.Count(SensorIds)
        then error "Supply verified, distinct sensor IDs" else SensorIds,
    Rows = Table.FromRecords(List.Combine(List.Transform(Checked, ForSensor)),
        type table[sensor_id=Int64.Type,page=Int64.Type,result_count=Int64.Type,payload_json=text]),
    WithSource = Table.AddColumn(Rows, "source", each "openaq_hourly", type text),
    WithStart = Table.AddColumn(WithSource, "requested_from_utc", each FromUtc, type text),
    WithEnd = Table.AddColumn(WithStart, "requested_to_utc", each ToUtc, type text),
    WithRun = Table.AddColumn(WithEnd, "run_id", each RunId, type text),
    WithTime = Table.AddColumn(WithRun, "ingested_at_utc", each ExtractedAt, type datetime)
in
    WithTime
