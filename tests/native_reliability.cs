using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Threading;
using System.Windows.Forms;

internal static class NativeReliabilityTests
{
    private const string InstanceName = "Local\\PurpleDragonFoundation.BitcoinMinerStudio.SmokeTest";
    private static object Call(MainForm form, string name, params object[] args)
    {
        return typeof(MainForm).GetMethod(name, BindingFlags.NonPublic | BindingFlags.Instance).Invoke(form, args);
    }
    private static void Assert(bool value, string message)
    {
        if (!value) throw new Exception(message);
        Console.WriteLine("PASS: " + message);
    }
    private static int HostMain()
    {
        return (int)typeof(Program).GetMethod("Main", BindingFlags.NonPublic | BindingFlags.Static)
            .Invoke(null, new object[] { new string[] { "--smoke-test" } });
    }

    [STAThread]
    private static int Main(string[] args)
    {
        if (args.Length == 2 && args[0] == "--hold")
        {
            using (var mutex = new Mutex(false, InstanceName))
            {
                if (!mutex.WaitOne(0)) return 3;
                File.WriteAllText(args[1], "ready");
                Thread.Sleep(40000);
                mutex.ReleaseMutex();
            }
            return 0;
        }
        string ready = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "mutex-ready.txt");
        if (File.Exists(ready)) File.Delete(ready);
        try
        {
            var info = new ProcessStartInfo
            {
                FileName = Assembly.GetExecutingAssembly().Location,
                Arguments = "--hold \"" + ready + "\"",
                UseShellExecute = false, CreateNoWindow = true, WindowStyle = ProcessWindowStyle.Hidden
            };
            // Keep an external reference so killing the owner leaves an abandoned mutex.
            using (var reference = new Mutex(false, InstanceName))
            using (var holder = Process.Start(info))
            {
                try
                {
                    var timer = Stopwatch.StartNew();
                    while (!File.Exists(ready) && timer.ElapsedMilliseconds < 5000) Thread.Sleep(25);
                    Assert(File.Exists(ready), "external mutex owner starts");
                    Assert(HostMain() == 2, "second native host exits before backend startup");
                    holder.Kill();
                    holder.WaitForExit();
                    Assert(HostMain() == 1, "abandoned mutex recovers and missing runtime fails safely");
                }
                finally { if (!holder.HasExited) { holder.Kill(); holder.WaitForExit(); } }
            }
            using (var form = new MainForm(true))
            {
                var flags = BindingFlags.Instance | BindingFlags.NonPublic;
                var tray = (NotifyIcon)typeof(MainForm).GetField("_trayIcon", flags).GetValue(form);
                typeof(MainForm).GetField("_closeToTray", flags).SetValue(form, true);
                Assert(!(bool)Call(form, "CanHideToTray"), "hidden tray cannot receive a hidden window");
                tray.Visible = true;
                Assert((bool)Call(form, "CanHideToTray"), "visible tray permits background lifecycle");
                var close = new FormClosingEventArgs(CloseReason.UserClosing, false);
                Call(form, "HandleFormClosing", form, close);
                Assert(close.Cancel, "close-to-tray cancels close when tray is available");
                tray.Visible = false;
                close = new FormClosingEventArgs(CloseReason.UserClosing, false);
                Call(form, "HandleFormClosing", form, close);
                Assert(!close.Cancel, "disabled tray allows real shutdown");
                Assert(typeof(MainForm).GetField("_trayIcon", flags).GetValue(form) == null, "shutdown disposes tray resources");
            }
            Console.WriteLine("All native reliability regressions passed.");
            return 0;
        }
        catch (Exception error) { Console.Error.WriteLine(error); return 1; }
        finally { if (File.Exists(ready)) File.Delete(ready); }
    }
}
