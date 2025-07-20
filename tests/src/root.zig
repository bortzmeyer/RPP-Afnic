const std = @import("std");
const testing = std.testing;
const Encoder = std.base64.Base64Encoder;

// The API we use
const ref_url = "http://localhost:8080/domains/";

// Some values
const headers_max_size = 1024;
const body_max_size = 65536;
const loginpassword = "2:qwerty";
const jsonoption = std.json.StringifyOptions{ .whitespace = .minified };

// Types
const Domain = struct { holder: u32, tech: u32, admin: u32 };
const Result = struct { status_code: std.http.Status, data: *std.json.Value };

var root: std.json.Value = std.json.Value.parseFromNumberSlice("0");

pub fn do_domain(domain: []const u8, method: std.http.Method, data: ?[]const u8) !Result {

    // We need an allocator for many things
    var gpa_impl = std.heap.GeneralPurposeAllocator(.{}){};
    defer _ = gpa_impl.deinit();
    const gpa = gpa_impl.allocator();

    var fullurl = try gpa.alloc(u8, ref_url.len + domain.len);
    defer gpa.free(fullurl);
    std.mem.copyForwards(u8, fullurl[0..], ref_url);
    std.mem.copyForwards(u8, fullurl[ref_url.len..], domain);
    const url = try std.Uri.parse(fullurl);

    var client = std.http.Client{ .allocator = gpa };
    defer client.deinit();

    var hbuffer: [headers_max_size]u8 = undefined;
    const pad: ?u8 = 61;
    const encoder = Encoder.init(std.base64.url_safe_alphabet_chars, pad);

    // Compute the authorization value
    const dest = try gpa.alloc(u8, encoder.calcSize(loginpassword.len));
    defer gpa.free(dest);
    _ = Encoder.encode(&encoder, dest, loginpassword);
    const prefix = "Basic ";
    var auth = try gpa.alloc(u8, prefix.len + dest.len);
    defer gpa.free(auth);
    std.mem.copyForwards(u8, auth[0..], prefix);
    std.mem.copyForwards(u8, auth[prefix.len..], dest);

    const headers = [_]std.http.Header{ std.http.Header{ .name = "Accept", .value = "application/rpp+json" }, std.http.Header{ .name = "User-Agent", .value = "RPPafnicClient/0.0" }, std.http.Header{ .name = "RPP-cltrid", .value = "654321" }, std.http.Header{ .name = "Authorization", .value = auth } };
    const options = std.http.Client.RequestOptions{ .server_header_buffer = &hbuffer, .extra_headers = &headers };

    // Call the API endpoint
    var request = try client.open(method, url, options);
    defer request.deinit();
    var adata: []const u8 = "";
    if (method == std.http.Method.PUT) {
        adata = data orelse return error.INeedData;
        request.transfer_encoding = .{ .content_length = adata.len };
    }
    _ = try request.send();
    if (method == std.http.Method.PUT) {
        _ = try request.writeAll(adata);
    }
    _ = try request.finish();
    _ = try request.wait();

    // Read the body
    var bbuffer: [body_max_size]u8 = undefined;
    _ = try request.readAll(&bbuffer);
    const blength = request.response.content_length orelse return error.NoBodyLength; // We trust
    // the Content-Length returned by the server…

    // Parse the JSON
    var parsed = try std.json.parseFromSlice(std.json.Value, gpa, bbuffer[0..blength], .{});
    defer parsed.deinit();
    root = parsed.value;

    return .{ .status_code = request.response.status, .data = &root };
}

test "basic read functionality" {
    const result = try do_domain("nic.example", std.http.Method.GET, null);
    try testing.expect(result.status_code == std.http.Status.ok);
}

test "non-existing domain" {
    const result = try do_domain("doesnotexist.example", std.http.Method.GET, null);
    try testing.expect(result.status_code == std.http.Status.not_found);
}

test "create domain" {
    const d = Domain{ .holder = 2, .tech = 2, .admin = 2 };
    var gpa_impl = std.heap.GeneralPurposeAllocator(.{}){};
    defer _ = gpa_impl.deinit();
    const gpa = gpa_impl.allocator();
    var payload = std.ArrayList(u8).init(gpa);
    defer payload.deinit();
    _ = try std.json.fmt(d, jsonoption).format("", .{}, payload.writer());
    const result = try do_domain("iguana.example", std.http.Method.PUT, payload.items);
    try testing.expect(result.status_code == std.http.Status.created);
}
