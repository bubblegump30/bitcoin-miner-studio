using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using System.Text;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

[assembly: System.Reflection.AssemblyTitle("Bitcoin Miner Studio")]
[assembly: System.Reflection.AssemblyProduct("Bitcoin Miner Studio")]
[assembly: System.Reflection.AssemblyCompany("Purple Dragon Foundation ltd")]
[assembly: System.Reflection.AssemblyVersion("__BMS_ASSEMBLY_VERSION__")]
[assembly: System.Reflection.AssemblyFileVersion("__BMS_ASSEMBLY_VERSION__")]

internal sealed class MainForm : Form
{
    private readonly string _root;
    private readonly string _runtimeRoot;
    private readonly string _bridgePath;
    private readonly bool _smokeTest;
    private readonly WebView2 _webView;
    private readonly Label _startupLabel;
    private readonly Stopwatch _startupWatch = Stopwatch.StartNew();
    private readonly TaskCompletionSource<bool> _backendReady = new TaskCompletionSource<bool>();
    private Process _backend;
    private StreamWriter _backendInput;
    private bool _forceExit;
    private bool _minimizeToTray = true;
    private bool _closeToTray;
    private bool _navigationReady;

    public int ExitCode { get; private set; }

    public MainForm(bool smokeTest)
    {
        _smokeTest = smokeTest;
        _root = AppDomain.CurrentDomain.BaseDirectory;
        _runtimeRoot = Path.Combine(_root, "_runtime");
        _bridgePath = Path.Combine(_runtimeRoot, "bms_native_bridge.py");

        Text = "Bitcoin Miner Studio v2.0.1";
        StartPosition = FormStartPosition.CenterScreen;
        Width = 1580;
        Height = 960;
        MinimumSize = new Size(1180, 760);
        BackColor = Color.FromArgb(7, 6, 11);

        try
        {
            Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath);
        }
        catch { }

        _startupLabel = new Label
        {
            Dock = DockStyle.Fill,
            Text = "Starting Bitcoin Miner Studio…",
            TextAlign = ContentAlignment.MiddleCenter,
            ForeColor = Color.FromArgb(220, 205, 255),
            BackColor = Color.FromArgb(7, 6, 11),
            Font = new Font("Segoe UI", 16.0f, FontStyle.Bold)
        };

        _webView = new WebView2
        {
            Dock = DockStyle.Fill,
            Visible = false,
            BackColor = Color.FromArgb(7, 6, 11)
        };

        Controls.Add(_webView);
        Controls.Add(_startupLabel);

        Shown += async (sender, args) => await InitializeAsync();
        Resize += HandleResize;
        FormClosing += HandleFormClosing;
    }

    private static string Sha256File(string path)
    {
        using (var sha = SHA256.Create())
        using (var stream = File.OpenRead(path))
        {
            return BitConverter.ToString(sha.ComputeHash(stream)).Replace("-", "").ToLowerInvariant();
        }
    }

    private void StartBackend()
    {
        string python = Path.Combine(_runtimeRoot, "python.exe");
        if (!File.Exists(python))
            throw new FileNotFoundException("The embedded Python runtime is missing.", python);
        if (!File.Exists(_bridgePath))
            throw new FileNotFoundException("The native Python bridge is missing.", _bridgePath);

        string bridgeHash = Sha256File(_bridgePath);
        if (!string.Equals(bridgeHash, "__BMS_BRIDGE_SHA256__", StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException("The native Python bridge failed its release hash check.");

        var psi = new ProcessStartInfo
        {
            FileName = python,
            Arguments = "-u \"" + _bridgePath + "\"",
            WorkingDirectory = _root,
            UseShellExecute = false,
            CreateNoWindow = true,
            WindowStyle = ProcessWindowStyle.Hidden,
            RedirectStandardInput = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true
        };
        psi.EnvironmentVariables["PYTHONHOME"] = _runtimeRoot;
        psi.EnvironmentVariables["PYTHONNOUSERSITE"] = "1";
        psi.EnvironmentVariables["PYTHONUTF8"] = "1";

        _backend = new Process { StartInfo = psi, EnableRaisingEvents = true };
        _backend.OutputDataReceived += BackendOutput;
        _backend.ErrorDataReceived += BackendError;
        _backend.Exited += BackendExited;
        if (!_backend.Start())
            throw new InvalidOperationException("Could not start the Bitcoin Miner Studio backend.");

        _backendInput = _backend.StandardInput;
        _backendInput.AutoFlush = true;
        _backend.BeginOutputReadLine();
        _backend.BeginErrorReadLine();
    }

    private async Task InitializeAsync()
    {
        try
        {
            StartBackend();

            string webViewData = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "PurpleDragonFoundation", "BitcoinMinerStudio", "WebView2");
            Directory.CreateDirectory(webViewData);

            Task<CoreWebView2Environment> environmentTask = CoreWebView2Environment.CreateAsync(null, webViewData);
            Task delay = Task.Delay(15000);
            Task ready = await Task.WhenAny(_backendReady.Task, delay);
            if (ready != _backendReady.Task)
                throw new TimeoutException("The Bitcoin Miner Studio backend did not become ready within 15 seconds.");
            await _backendReady.Task;

            CoreWebView2Environment environment = await environmentTask;
            await _webView.EnsureCoreWebView2Async(environment);

            _webView.CoreWebView2.Settings.AreDevToolsEnabled = false;
            _webView.CoreWebView2.Settings.AreDefaultContextMenusEnabled = false;
            _webView.CoreWebView2.Settings.IsStatusBarEnabled = false;
            _webView.CoreWebView2.Settings.IsZoomControlEnabled = true;

            string uiRoot = Path.Combine(_root, "ui");
            if (!Directory.Exists(uiRoot))
                throw new DirectoryNotFoundException("The Bitcoin Miner Studio UI folder is missing.");

            _webView.CoreWebView2.SetVirtualHostNameToFolderMapping(
                "app.bms",
                uiRoot,
                CoreWebView2HostResourceAccessKind.Allow);

            _webView.CoreWebView2.WebMessageReceived += WebMessageReceived;
            _webView.CoreWebView2.NavigationCompleted += NavigationCompleted;
            await _webView.CoreWebView2.AddScriptToExecuteOnDocumentCreatedAsync(BridgeBootstrapScript());
            _webView.Source = new Uri("https://app.bms/index.html");
        }
        catch (WebView2RuntimeNotFoundException)
        {
            FailStartup("Microsoft Edge WebView2 Runtime is not installed. Install or repair Microsoft Edge WebView2 Runtime, then start Bitcoin Miner Studio again.");
        }
        catch (Exception ex)
        {
            FailStartup(ex.ToString());
        }
    }

    private string BridgeBootstrapScript()
    {
        return @"
(function () {
  if (window.__bmsNativeBridgeInstalled) return;
  window.__bmsNativeBridgeInstalled = true;
  const pending = new Map();
  let sequence = 0;

  window.__bmsBridgeReceive = function (message) {
    if (!message) return;
    const id = String(message.id == null ? '' : message.id);
    const item = pending.get(id);
    if (!item) return;
    pending.delete(id);
    if (message.ok) item.resolve(message.result);
    else item.reject(new Error(message.error || 'Bitcoin Miner Studio backend call failed.'));
  };

  const api = new Proxy({}, {
    get: function (_target, property) {
      if (property === 'then') return undefined;
      if (typeof property !== 'string') return undefined;
      return function () {
        const args = Array.prototype.slice.call(arguments);
        return new Promise(function (resolve, reject) {
          const id = 'native-' + (++sequence);
          pending.set(id, { resolve: resolve, reject: reject });
          chrome.webview.postMessage({ type: 'call', id: id, method: property, args: args });
        });
      };
    }
  });

  window.pywebview = window.pywebview || {};
  window.pywebview.api = api;

  window.addEventListener('DOMContentLoaded', function () {
    try { window.dispatchEvent(new Event('pywebviewready')); } catch (_) {}
    try { document.dispatchEvent(new Event('pywebviewready')); } catch (_) {}
  }, { once: true });
})();";
    }

    private static Dictionary<string, object> ParseObject(string json)
    {
        return new JavaScriptSerializer().Deserialize<Dictionary<string, object>>(json);
    }

    private static string JsonString(string value)
    {
        return new JavaScriptSerializer().Serialize(value);
    }

    private void BackendOutput(object sender, DataReceivedEventArgs e)
    {
        if (string.IsNullOrWhiteSpace(e.Data)) return;
        string line = e.Data;
        try
        {
            Dictionary<string, object> message = ParseObject(line);
            string type = message.ContainsKey("type") ? Convert.ToString(message["type"]) : "";

            if (type == "ready")
            {
                _backendReady.TrySetResult(true);
                return;
            }
            if (type == "fatal")
            {
                string error = message.ContainsKey("traceback") ? Convert.ToString(message["traceback"]) : Convert.ToString(message["error"]);
                _backendReady.TrySetException(new InvalidOperationException(error));
                BeginInvoke(new Action(() => FailStartup(error)));
                return;
            }
            if (type == "response")
            {
                BeginInvoke(new Action(async () =>
                {
                    if (_webView.CoreWebView2 == null) return;
                    string literal = JsonString(line);
                    await _webView.CoreWebView2.ExecuteScriptAsync("window.__bmsBridgeReceive(JSON.parse(" + literal + ")); ");
                }));
                return;
            }
            if (type == "host_request")
            {
                BeginInvoke(new Action(() => HandleHostRequest(message)));
                return;
            }
            if (type == "host_event")
            {
                BeginInvoke(new Action(() => HandleHostEvent(message)));
            }
        }
        catch (Exception ex)
        {
            AppendBackendLog("Protocol parse error: " + ex + Environment.NewLine + line);
        }
    }

    private void BackendError(object sender, DataReceivedEventArgs e)
    {
        if (!string.IsNullOrWhiteSpace(e.Data))
            AppendBackendLog(e.Data);
    }

    private void BackendExited(object sender, EventArgs e)
    {
        if (_forceExit) return;
        try
        {
            if (_backend != null && _backend.ExitCode != 0)
                BeginInvoke(new Action(() => FailStartup("The Bitcoin Miner Studio backend exited unexpectedly with code " + _backend.ExitCode + ". Check native-backend.log for details.")));
        }
        catch { }
    }

    private void AppendBackendLog(string text)
    {
        try
        {
            lock (this)
            {
                File.AppendAllText(Path.Combine(_root, "native-backend.log"), text + Environment.NewLine, Encoding.UTF8);
            }
        }
        catch { }
    }

    private void SendBackendObject(Dictionary<string, object> payload)
    {
        try
        {
            if (_backendInput == null) return;
            string json = new JavaScriptSerializer().Serialize(payload);
            lock (_backendInput)
            {
                _backendInput.WriteLine(json);
                _backendInput.Flush();
            }
        }
        catch (Exception ex)
        {
            AppendBackendLog("Could not send bridge message: " + ex);
        }
    }

    private void WebMessageReceived(object sender, CoreWebView2WebMessageReceivedEventArgs e)
    {
        string raw = e.WebMessageAsJson;
        Dictionary<string, object> message;
        try { message = ParseObject(raw); }
        catch { return; }

        string type = message.ContainsKey("type") ? Convert.ToString(message["type"]) : "";
        if (type == "smoke_result")
        {
            bool ok = message.ContainsKey("ok") && Convert.ToBoolean(message["ok"]);
            CompleteSmoke(ok, message.ContainsKey("error") ? Convert.ToString(message["error"]) : "");
            return;
        }

        if (type == "call")
        {
            try
            {
                if (_backendInput != null)
                {
                    lock (_backendInput)
                    {
                        _backendInput.WriteLine(raw);
                        _backendInput.Flush();
                    }
                }
            }
            catch (Exception ex)
            {
                AppendBackendLog("Bridge send failed: " + ex);
            }
        }
    }

    private async void NavigationCompleted(object sender, CoreWebView2NavigationCompletedEventArgs e)
    {
        if (!e.IsSuccess)
        {
            FailStartup("The local Bitcoin Miner Studio interface could not be loaded: " + e.WebErrorStatus);
            return;
        }

        _navigationReady = true;
        _startupLabel.Visible = false;
        _webView.Visible = true;
        _webView.BringToFront();

        if (_smokeTest)
        {
            await Task.Delay(350);
            await _webView.CoreWebView2.ExecuteScriptAsync(@"
(async function () {
  try {
    const value = await window.pywebview.api.get_bootstrap();
    chrome.webview.postMessage({type:'smoke_result', ok: !!value});
  } catch (error) {
    chrome.webview.postMessage({type:'smoke_result', ok:false, error:String(error && error.message || error)});
  }
})();");
        }
    }

    private void CompleteSmoke(bool ok, string error)
    {
        try
        {
            string json = "{\"ok\":" + (ok ? "true" : "false") + ",\"startup_ms\":" + _startupWatch.ElapsedMilliseconds + ",\"transport\":\"native-webview2-stdio\"}";
            File.WriteAllText(Path.Combine(_root, "native-smoke.json"), json, Encoding.UTF8);
        }
        catch { }

        ExitCode = ok ? 0 : 9;
        if (!ok && !string.IsNullOrWhiteSpace(error))
            AppendBackendLog("Smoke test failed: " + error);
        _forceExit = true;
        Close();
    }

    private void HandleHostRequest(Dictionary<string, object> message)
    {
        string action = message.ContainsKey("action") ? Convert.ToString(message["action"]) : "";
        string requestId = message.ContainsKey("id") ? Convert.ToString(message["id"]) : "";

        var response = new Dictionary<string, object>
        {
            { "type", "host_response" },
            { "id", requestId },
            { "ok", true },
            { "selected", null }
        };

        try
        {
            if (action != "file_dialog")
                throw new InvalidOperationException("Unsupported native host request: " + action);

            int dialogType = Convert.ToInt32(message["dialog_type"]);
            if (dialogType == 20)
            {
                using (var dialog = new FolderBrowserDialog())
                {
                    dialog.Description = "Select folder";
                    dialog.ShowNewFolderButton = false;
                    if (dialog.ShowDialog(this) == DialogResult.OK)
                        response["selected"] = new[] { dialog.SelectedPath };
                }
            }
            else
            {
                using (var dialog = new OpenFileDialog())
                {
                    dialog.Title = "Select file";
                    dialog.CheckFileExists = true;
                    dialog.Multiselect = message.ContainsKey("allow_multiple") && Convert.ToBoolean(message["allow_multiple"]);
                    dialog.Filter = BuildFileFilter(message.ContainsKey("file_types") ? message["file_types"] : null);
                    if (dialog.ShowDialog(this) == DialogResult.OK)
                        response["selected"] = dialog.FileNames;
                }
            }
        }
        catch (Exception ex)
        {
            response["ok"] = false;
            response["error"] = ex.Message;
        }

        SendBackendObject(response);
    }

    private static string BuildFileFilter(object raw)
    {
        var filters = new List<string>();
        object[] entries = raw as object[];
        if (entries != null)
        {
            foreach (object item in entries)
            {
                string text = Convert.ToString(item) ?? "";
                int open = text.LastIndexOf('(');
                int close = text.LastIndexOf(')');
                if (open > 0 && close > open)
                {
                    string label = text.Substring(0, open).Trim();
                    string pattern = text.Substring(open + 1, close - open - 1).Trim();
                    if (!string.IsNullOrWhiteSpace(label) && !string.IsNullOrWhiteSpace(pattern))
                    {
                        filters.Add(label);
                        filters.Add(pattern);
                    }
                }
            }
        }
        filters.Add("All files");
        filters.Add("*.*");
        return string.Join("|", filters.ToArray());
    }

    private void HandleHostEvent(Dictionary<string, object> message)
    {
        string action = message.ContainsKey("action") ? Convert.ToString(message["action"]) : "";
        if (action == "show_window")
        {
            Show();
            WindowState = FormWindowState.Normal;
            Activate();
            return;
        }
        if (action == "hide_window")
        {
            Hide();
            return;
        }
        if (action == "exit_app")
        {
            _forceExit = true;
            Close();
            return;
        }
        if (action == "tray_state" && message.ContainsKey("tray"))
        {
            var tray = message["tray"] as Dictionary<string, object>;
            if (tray == null) return;
            var settings = tray.ContainsKey("settings") ? tray["settings"] as Dictionary<string, object> : null;
            if (settings == null) return;
            if (settings.ContainsKey("tray_minimize_to_tray"))
                _minimizeToTray = Convert.ToBoolean(settings["tray_minimize_to_tray"]);
            if (settings.ContainsKey("tray_close_to_tray"))
                _closeToTray = Convert.ToBoolean(settings["tray_close_to_tray"]);
        }
    }

    private void HandleResize(object sender, EventArgs e)
    {
        if (WindowState == FormWindowState.Minimized && _minimizeToTray)
            Hide();
    }

    private void HandleFormClosing(object sender, FormClosingEventArgs e)
    {
        if (!_forceExit && _closeToTray && e.CloseReason == CloseReason.UserClosing)
        {
            e.Cancel = true;
            Hide();
            return;
        }
        _forceExit = true;
        ShutdownBackend();
    }

    private void ShutdownBackend()
    {
        try
        {
            if (_backendInput != null && _backend != null && !_backend.HasExited)
            {
                SendBackendObject(new Dictionary<string, object> { { "type", "shutdown" } });
                if (!_backend.WaitForExit(2500))
                    _backend.Kill();
            }
        }
        catch
        {
            try { if (_backend != null && !_backend.HasExited) _backend.Kill(); } catch { }
        }
    }

    private void FailStartup(string details)
    {
        try
        {
            File.WriteAllText(Path.Combine(_root, "startup-error.log"), details, Encoding.UTF8);
        }
        catch { }

        ExitCode = 1;
        _forceExit = true;
        if (!_smokeTest)
            MessageBox.Show(this, "Bitcoin Miner Studio could not start.\n\n" + details, "Bitcoin Miner Studio", MessageBoxButtons.OK, MessageBoxIcon.Error);
        Close();
    }
}

internal static class Program
{
    [STAThread]
    private static int Main(string[] args)
    {
        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);
        bool smoke = args.Any(a => string.Equals(a, "--smoke-test", StringComparison.OrdinalIgnoreCase));
        using (var form = new MainForm(smoke))
        {
            Application.Run(form);
            return form.ExitCode;
        }
    }
}
