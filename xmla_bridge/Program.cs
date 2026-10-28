using System.Data.Common;
using System.Globalization;
using System.Text.Json;
using System.Text.RegularExpressions;
using Microsoft.AnalysisServices.AdomdClient;

// One JSON request on stdin, one response on stdout. No logs, token arguments,
// token persistence, REST fallback, ExecuteNonQuery, TOM, roles or impersonation.
internal static class Program
{
    private static readonly JsonSerializerOptions Json = new() { PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower };
    private static readonly HashSet<string> Forbidden = new(StringComparer.OrdinalIgnoreCase)
    {
        "ALTER", "CREATE", "DELETE", "DROP", "INSERT", "UPDATE", "MERGE", "REFRESH",
        "PROCESS", "EXECUTE", "CALL", "CLEAR", "ATTACH", "DETACH", "BACKUP",
        "RESTORE", "SELECT", "DRILLTHROUGH"
    };

    private sealed record Request(
        int Version, string Server, string Catalog, string Dax,
        int MaxRows, int TimeoutSeconds, string Token, long ExpiresOn);

    public static int Main()
    {
        Request? request = null;
        try
        {
            request = JsonSerializer.Deserialize<Request>(Console.In.ReadToEnd(), Json)
                ?? throw new ArgumentException();
            Validate(request);
            Run(request);
            return 0;
        }
        catch (Exception ex)
        {
            // Never emit raw exceptions, stack traces, token/header payloads or DAX.
            string message = ex.Message.ToLowerInvariant();
            string code = ex switch
            {
                ArgumentException or JsonException => "validation",
                TimeoutException => "timeout",
                _ when message.Contains("unauthorized") || message.Contains("forbidden")
                    || message.Contains("401") || message.Contains("403")
                    || message.Contains("authentication") => "auth",
                _ when message.Contains("timeout") || message.Contains("timed out") => "timeout",
                _ when message.Contains("429") || message.Contains("503")
                    || message.Contains("temporarily unavailable")
                    || ex is System.Net.Http.HttpRequestException or System.Net.Sockets.SocketException => "transient",
                AdomdException => "query",
                _ => "internal"
            };
            var diagnostics = new List<object>();
            for (Exception? current = ex; current is not null && diagnostics.Count < 4; current = current.InnerException)
                diagnostics.Add(new {
                    type = current.GetType().Name,
                    hresult = $"0x{current.HResult:X8}",
                    message = code == "validation" ? "Invalid bridge request or read-only DAX." : Sanitize(current.Message, request)
                });
            Console.Out.Write(JsonSerializer.Serialize(new { version = 1, ok = false, error = code, diagnostics }));
            return 1;
        }
    }

    private static string Sanitize(string message, Request? request)
    {
        if (request is not null)
        {
            if (!string.IsNullOrEmpty(request.Token)) message = message.Replace(request.Token, "[REDACTED]");
            if (!string.IsNullOrEmpty(request.Dax)) message = message.Replace(request.Dax, "[DAX]");
        }
        message = Regex.Replace(message, @"[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]+", "[JWT]");
        message = Regex.Replace(message, @"(?i)\b(Bearer\s+)\S+", "$1[REDACTED]");
        message = Regex.Replace(message, @"(?i)\b(password|pwd|token|authorization|client_secret|access_token)\s*[""']?\s*[:=]\s*[^;\r\n]+", "$1=[REDACTED]");
        message = Regex.Replace(message, @"[\r\n\t]+", " ");
        return message.Length > 1200 ? message[..1200] + "..." : message;
    }

    private static void Validate(Request r)
    {
        if (r.Version != 1 || r.Server is null || !Regex.IsMatch(r.Server,
            @"\Apowerbi://api\.powerbi\.com/v1\.0/myorg/[A-Za-z0-9._~%\-]+\z")
            || Regex.IsMatch(r.Server, @"%(?![0-9a-fA-F]{2})"))
            throw new ArgumentException();
        string segment = Uri.UnescapeDataString(r.Server[(r.Server.LastIndexOf('/') + 1)..]);
        if (string.IsNullOrWhiteSpace(segment) || segment is "." or ".." || segment.Any(char.IsControl)
            || string.IsNullOrWhiteSpace(r.Catalog) || r.Catalog.Length > 1024 || r.Catalog.Any(char.IsControl)
            || r.MaxRows < 1 || r.MaxRows > 10000 || r.TimeoutSeconds < 1 || r.TimeoutSeconds > 60
            || string.IsNullOrWhiteSpace(r.Token)
            || r.ExpiresOn <= DateTimeOffset.UtcNow.ToUnixTimeSeconds())
            throw new ArgumentException();
        ValidateDax(r.Dax);
    }

    private static void ValidateDax(string dax)
    {
        if (string.IsNullOrWhiteSpace(dax) || dax.Length > 100000 || dax.Contains('\0'))
            throw new ArgumentException();
        var tokens = new List<string>();
        int i = 0;
        while (i < dax.Length)
        {
            if (i + 1 < dax.Length && (dax.Substring(i, 2) is "//" or "--"))
            {
                int end = dax.IndexOf('\n', i + 2);
                i = end < 0 ? dax.Length : end + 1;
            }
            else if (i + 1 < dax.Length && dax.Substring(i, 2) == "/*")
            {
                int end = dax.IndexOf("*/", i + 2, StringComparison.Ordinal);
                if (end < 0) throw new ArgumentException();
                i = end + 2;
            }
            else if (dax[i] is '"' or '\'' or '[')
            {
                char closing = dax[i] == '[' ? ']' : dax[i];
                i++;
                while (true)
                {
                    int end = dax.IndexOf(closing, i);
                    if (end < 0) throw new ArgumentException();
                    i = end + 1;
                    if (i < dax.Length && dax[i] == closing) i++;
                    else break;
                }
                tokens.Add("QUOTED");
            }
            else if (char.IsLetter(dax[i]) || dax[i] == '_')
            {
                int start = i++;
                while (i < dax.Length && (char.IsLetterOrDigit(dax[i]) || dax[i] is '_' or '.')) i++;
                tokens.Add(dax[start..i].ToUpperInvariant());
            }
            else if (char.IsWhiteSpace(dax[i])) i++;
            else
            {
                if (dax[i] == ';') throw new ArgumentException();
                tokens.Add(dax[i++].ToString());
            }
        }
        if (tokens.Count == 0 || tokens[0] is not ("EVALUATE" or "DEFINE")
            || tokens.Count(t => t == "EVALUATE") != 1 || tokens.Count(t => t == "DEFINE") > 1
            || tokens.Any(Forbidden.Contains))
            throw new ArgumentException();
    }

    private static void Run(Request r)
    {
        // Builder quotes catalog names, preventing connection-string injection.
        var builder = new DbConnectionStringBuilder
        {
            ["Data Source"] = r.Server,
            ["Initial Catalog"] = r.Catalog,
            ["Integrated Security"] = "ClaimsToken",
            ["Connect Timeout"] = r.TimeoutSeconds,
            ["Application Name"] = "LocalReadOnlyXmlaBridge"
        };
        using var connection = new AdomdConnection(builder.ConnectionString);
        connection.AccessToken = new Microsoft.AnalysisServices.AccessToken(
            r.Token, DateTimeOffset.FromUnixTimeSeconds(r.ExpiresOn), null);
        connection.Open();
        using var command = connection.CreateCommand();
        command.CommandText = r.Dax;
        command.CommandTimeout = r.TimeoutSeconds;
        using var reader = command.ExecuteReader();
        var columns = Enumerable.Range(0, reader.FieldCount)
            .Select(i => new { name = reader.GetName(i), type = reader.GetFieldType(i).Name }).ToArray();
        var rows = new List<object?[]>();
        bool truncated = false;
        while (reader.Read())
        {
            // Read one extra row to distinguish an exact-cap result from truncation.
            if (rows.Count == r.MaxRows) { truncated = true; break; }
            var row = new object?[reader.FieldCount];
            for (int i = 0; i < row.Length; i++)
                row[i] = reader.IsDBNull(i) ? null : Encode(reader.GetValue(i));
            rows.Add(row);
        }
        Console.Out.Write(JsonSerializer.Serialize(new { version = 1, ok = true, columns, rows, truncated }));
    }

    private static object? Encode(object value) => value switch
    {
        DBNull => null,
        decimal d => d.ToString(CultureInfo.InvariantCulture),
        DateTime d => d.ToString("O", CultureInfo.InvariantCulture),
        DateTimeOffset d => d.ToString("O", CultureInfo.InvariantCulture),
        byte[] b => Convert.ToBase64String(b),
        double d when !double.IsFinite(d) => d.ToString(CultureInfo.InvariantCulture),
        float f when !float.IsFinite(f) => f.ToString(CultureInfo.InvariantCulture),
        string or bool or byte or sbyte or short or ushort or int or uint or long or ulong
            or float or double => value,
        _ => Convert.ToString(value, CultureInfo.InvariantCulture)
    };
}
