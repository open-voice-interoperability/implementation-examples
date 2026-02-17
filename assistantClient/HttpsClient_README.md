# HTTPS Client Class for C++

A simple C++ class for making HTTPS POST requests with JSON input and output.

## Dependencies

This class requires:
- **libcurl**: For HTTP/HTTPS requests
- **nlohmann/json**: For JSON parsing

## Installation

### Windows (vcpkg)
```powershell
vcpkg install curl nlohmann-json
```

### Linux (Ubuntu/Debian)
```bash
sudo apt-get install libcurl4-openssl-dev nlohmann-json3-dev
```

### macOS (Homebrew)
```bash
brew install curl nlohmann-json
```

## Compilation

### Windows (with vcpkg)
```powershell
cl test.cpp /I"C:\vcpkg\installed\x64-windows\include" /link curl.lib /LIBPATH:"C:\vcpkg\installed\x64-windows\lib"
```

### Linux/macOS
```bash
g++ -std=c++11 test.cpp -o https_client -lcurl
```

## Usage

```cpp
HttpsClient client;

// Set timeout (optional)
client.setTimeout(30);

// Prepare JSON input
json input;
input["username"] = "john_doe";
input["password"] = "secret123";

// Make POST request
json response = client.post("https://api.example.com/login", input);

// Check for errors
if (response.contains("error")) {
    std::cout << "Error: " << response["error"] << std::endl;
} else {
    std::cout << "Success: " << response.dump(2) << std::endl;
}
```

## Features

- ✅ HTTPS support with SSL/TLS verification
- ✅ JSON input/output handling
- ✅ Automatic error handling
- ✅ HTTP status code in response
- ✅ Configurable timeout
- ✅ Proper cleanup and resource management

## Class Methods

### `json post(const std::string& url, const json& input_json)`
Makes an HTTPS POST request with JSON data.

**Parameters:**
- `url`: The target URL
- `input_json`: JSON object to send as request body

**Returns:** JSON object containing the response (includes `http_code` field)

### `void setTimeout(long seconds)`
Sets the request timeout in seconds.

**Parameters:**
- `seconds`: Timeout duration
