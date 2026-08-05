/*
  Photoshop ExtendScript hook for launching the Shopify uploader GUI
  after export completes.

  Usage in your existing export script:

    #include "photoshop_post_export_hook.jsx"
    // ... your export logic ...
    maybeLaunchShopifyUploaderGUI(true);
*/

function maybeLaunchShopifyUploaderGUI(launchAfterExport) {
    if (!launchAfterExport) {
        return false;
    }

    // Update this path if your repo is in a different location.
    var uploaderRoot = Folder("~/Documents/GitHub/Moonbeam Merch Shopify Bulk Upload");
    if (!uploaderRoot.exists) {
        alert("Uploader folder not found:\n" + uploaderRoot.fsName);
        return false;
    }

    var isWindows = $.os.toLowerCase().indexOf("windows") >= 0;
    var launcher = isWindows
        ? File(uploaderRoot.fsName + "/run_gui_windows.bat")
        : File(uploaderRoot.fsName + "/run_gui_mac.command");

    if (!launcher.exists) {
        alert("Launcher not found:\n" + launcher.fsName);
        return false;
    }

    if (!isWindows) {
        // Ensure executable bit is present on macOS.
        try {
            app.system("chmod +x \"" + launcher.fsName + "\"");
        } catch (e) {
            // Non-fatal: continue and try to execute.
        }
    }

    var ok = launcher.execute();
    if (!ok) {
        alert("Failed to start uploader launcher:\n" + launcher.fsName);
    }
    return ok;
}
