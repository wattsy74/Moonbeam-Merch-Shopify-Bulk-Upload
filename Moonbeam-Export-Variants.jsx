// =====================================================
//  Photoshop Variant Export Script
//  Supports single-position and front/back workflows.
//  Front layers: prefix PFM*   Back layers: prefix PBM*
//  Writes pairings.json when front/back layers detected.
// =====================================================

// ---- CONFIG ----
var exportFolder = Folder.selectDialog("Choose export folder");
if (!exportFolder) {
    alert("No folder selected. Export cancelled.");
} else {

var smartObjectLayerName = "Artworks";
var excludeArtworks = ["DTG Printable Area Frame"];

// ---- HELPERS ----
function isExcluded(name, list) {
    for (var i = 0; i < list.length; i++) { if (list[i] == name) return true; }
    return false;
}

function findLayerRecursive(parent, name) {
    for (var i = 0; i < parent.layers.length; i++) {
        var layer = parent.layers[i];
        if (layer.name == name) return layer;
        if (layer.typename == "LayerSet") {
            var found = findLayerRecursive(layer, name);
            if (found) return found;
        }
    }
    return null;
}

function setVisibilityRecursive(layer, visible) {
    layer.visible = visible;
    if (layer.typename == "LayerSet") {
        for (var i = 0; i < layer.layers.length; i++) setVisibilityRecursive(layer.layers[i], visible);
    }
}

function detectFoldersRecursive(parent, prefix) {
    var results = [];
    for (var i = 0; i < parent.layers.length; i++) {
        var lyr = parent.layers[i];
        if (lyr.typename == "LayerSet") {
            if (lyr.name.indexOf(prefix) == 0) results.push(lyr.name);
            var sub = detectFoldersRecursive(lyr, prefix);
            for (var j = 0; j < sub.length; j++) results.push(sub[j]);
        }
    }
    return results;
}

function detectArtworks(doc) {
    var arr = [];
    for (var i = 0; i < doc.layers.length; i++) {
        var lyr = doc.layers[i];
        if (!isExcluded(lyr.name, excludeArtworks)) arr.push(lyr.name);
    }
    return arr;
}

function exportFlattenedPNG(filename) {
    var dup = app.activeDocument.duplicate();
    var file = new File(exportFolder + "/" + filename + ".png");
    var opts = new ExportOptionsSaveForWeb();
    opts.format = SaveDocumentType.PNG;
    opts.PNG8 = false;
    opts.transparency = true;
    opts.interlaced = false;
    opts.includeProfile = false;
    dup.exportDocument(file, ExportType.SAVEFORWEB, opts);
    dup.close(SaveOptions.DONOTSAVECHANGES);
}

// ---- FRONT/BACK DETECTION ----

function detectStylePositions(styleFolder) {
    var hasFront = false, hasBack = false;
    for (var c = 0; c < styleFolder.layers.length; c++) {
        var col = styleFolder.layers[c];
        if (col.typename == "LayerSet") {
            for (var sl = 0; sl < col.layers.length; sl++) {
                var lyr = col.layers[sl];
                if (lyr.typename != "LayerSet") {
                    if (lyr.name.indexOf("PFM") == 0) hasFront = true;
                    if (lyr.name.indexOf("PBM") == 0) hasBack = true;
                }
            }
            break;
        }
    }
    return { hasFront: hasFront, hasBack: hasBack };
}

function psdHasFrontBackLayers(mainDoc, styleList) {
    for (var s = 0; s < styleList.length; s++) {
        var sf = findLayerRecursive(mainDoc, styleList[s]);
        if (sf) {
            var pos = detectStylePositions(sf);
            if (pos.hasFront || pos.hasBack) return true;
        }
    }
    return false;
}

// Extract style_code from first shirt layer inside the style folder
// e.g. "PFM0_STTU169_C001_Creator_2.0_White" -> "Creator_2.0"
function getStyleCodeFromFolder(styleFolder) {
    for (var c = 0; c < styleFolder.layers.length; c++) {
        var col = styleFolder.layers[c];
        if (col.typename == "LayerSet") {
            for (var sl = 0; sl < col.layers.length; sl++) {
                var lyr = col.layers[sl];
                if (lyr.typename != "LayerSet") {
                    var parts = lyr.name.split("_");
                    if (parts.length >= 5) {
                        var sp = [];
                        for (var p = 3; p < parts.length - 1; p++) sp.push(parts[p]);
                        return sp.join("_");
                    }
                    break;
                }
            }
            break;
        }
    }
    return styleFolder.name.replace("style_", "");
}

// "style_Creator2.0" -> "Creator 2.0"
function getStyleDisplayName(folderName) {
    var n = folderName.replace("style_", "");
    n = n.replace(/([a-z])([A-Z])/g, "$1 $2");
    n = n.replace(/([a-zA-Z])(\d)/g, "$1 $2");
    return n;
}

// ---- LAUNCH UPLOADER HELPER ----
function launchUploaderWithFolder(folderPath, autoUpload, publishActive) {
    var isWin = ($.os.toLowerCase().indexOf("windows") >= 0);
    var hPath = isWin ? "C:/Program Files/Moonbeam-Uploader/.launch_folder"
                      : "/Applications/Moonbeam-Uploader/.launch_folder";
    var hf = new File(hPath);
    hf.open("w");
    hf.write(folderPath);
    if (autoUpload)    hf.write("\nauto_upload=true");
    if (publishActive) hf.write("\npublish_active=true");
    hf.close();
    if (isWin) app.system('start "" "C:\\Program Files\\Moonbeam-Uploader\\run_gui_windows.bat"');
    else       app.system('open "/Applications/Moonbeam-Uploader/run_gui_mac.command"');
}

// ---- DIALOGS ----

function addLaunchOptions(dialog) {
    var lc = dialog.add("checkbox", undefined, "Launch Moonbeam Uploader when export completes");
    lc.value = false;
    var ac = dialog.add("checkbox", undefined, "    \u2514 Auto-upload immediately on launch");
    ac.value = false; ac.enabled = false;
    var pc = dialog.add("checkbox", undefined, "        \u2514 Publish as Active");
    pc.value = false; pc.enabled = false;
    lc.onClick = function() {
        ac.enabled = lc.value;
        if (!lc.value) { ac.value = false; pc.value = false; pc.enabled = false; }
    };
    ac.onClick = function() { pc.enabled = ac.value; if (!ac.value) pc.value = false; };
    return { launchCheck: lc, autoUploadCheck: ac, publishActiveCheck: pc };
}

function showStyleSelectionDialog(styleNames) {
    var dialog = new Window("dialog", "Select styles to export", [100, 100, 420, 420]);
    dialog.orientation = "column";
    dialog.alignChildren = "left";
    dialog.margins = 16;
    dialog.add("statictext", undefined, "Choose which styles to process:");
    var stylesPanel = dialog.add("panel", undefined, "Styles");
    stylesPanel.orientation = "column";
    stylesPanel.alignChildren = "left";
    stylesPanel.margins = 12;
    stylesPanel.alignment = ["fill", "top"];
    stylesPanel.minimumSize = [340, Math.max(120, styleNames.length * 26 + 20)];
    var checkboxes = [];
    for (var i = 0; i < styleNames.length; i++) {
        var cb = stylesPanel.add("checkbox", undefined, styleNames[i]);
        cb.value = true;
        checkboxes.push(cb);
    }
    var lo = addLaunchOptions(dialog);
    var bg = dialog.add("group"); bg.alignment = "right";
    var ok = bg.add("button", undefined, "OK");
    var cancel = bg.add("button", undefined, "Cancel");
    ok.onClick = function() { dialog.close(1); };
    cancel.onClick = function() { dialog.close(2); };
    dialog.layout.layout(true); dialog.layout.resize(); dialog.center();
    if (dialog.show() != 1) return null;
    var sel = [];
    for (var i = 0; i < checkboxes.length; i++) { if (checkboxes[i].value) sel.push(styleNames[i]); }
    return { styles: sel, launchUploader: lo.launchCheck.value, autoUpload: lo.autoUploadCheck.value, publishActive: lo.publishActiveCheck.value };
}

function showMatrixDialog(styleInfos, artworkNames) {
    var rows = [];
    for (var i = 0; i < styleInfos.length; i++) {
        var si = styleInfos[i];
        if (si.hasFront) rows.push({ label: si.displayName + " Front", styleName: si.styleName, styleCode: si.styleCode, position: "front" });
        if (si.hasBack)  rows.push({ label: si.displayName + " Back",  styleName: si.styleName, styleCode: si.styleCode, position: "back"  });
    }
    if (rows.length == 0) { alert("No front/back positions detected."); return null; }

    // Use single letters A/B/C... as column headers; full names shown in legend
    var colLabels = [];
    for (var a = 0; a < artworkNames.length; a++) {
        colLabels.push(artworkNames.length <= 26 ? String.fromCharCode(65 + a) : String(a + 1));
    }

    var LABEL_W = 190, COL_W = 28, ROW_H = 22, HROW_H = 22, PAD = 16;
    var gridW = LABEL_W + artworkNames.length * COL_W;
    var gridH = HROW_H + rows.length * ROW_H + 10;

    var dialog = new Window("dialog", "Front / Back Artwork Assignment");
    dialog.orientation = "column";
    dialog.alignChildren = ["fill", "top"];
    dialog.margins = [PAD, PAD, PAD, PAD];
    dialog.spacing = 8;

    // ---- Grid panel with absolute positioning for exact alignment ----
    var gp = dialog.add("panel", [0, 0, gridW + PAD, gridH + PAD]);
    gp.preferredSize = [gridW + PAD, gridH + PAD];

    var baseY = 8;
    gp.add("statictext", [4, baseY, LABEL_W, baseY + HROW_H], "Style / Position");
    for (var a = 0; a < colLabels.length; a++) {
        var hx = LABEL_W + a * COL_W;
        var hl = gp.add("statictext", [hx, baseY, hx + COL_W, baseY + HROW_H], colLabels[a]);
        hl.justify = "center";
    }

    var cbGrid = [];
    for (var r = 0; r < rows.length; r++) {
        (function(ri) {
            cbGrid.push([]);
            var ry = baseY + HROW_H + 4 + ri * ROW_H;
            gp.add("statictext", [4, ry + 3, LABEL_W - 2, ry + ROW_H], rows[ri].label);
            for (var a = 0; a < artworkNames.length; a++) {
                (function(ai) {
                    var cx = LABEL_W + ai * COL_W + Math.floor((COL_W - 14) / 2);
                    var cb = gp.add("checkbox", [cx, ry + 4, cx + 14, ry + 18], "");
                    cbGrid[ri].push(cb);
                    cb.onClick = function() {
                        if (cb.value) {
                            for (var xi = 0; xi < cbGrid[ri].length; xi++) {
                                if (xi !== ai) cbGrid[ri][xi].value = false;
                            }
                        }
                    };
                })(a);
            }
        })(r);
    }

    // ---- Legend ----
    var legendLines = [];
    for (var a = 0; a < artworkNames.length; a++) legendLines.push(colLabels[a] + " = " + artworkNames[a]);
    dialog.add("statictext", undefined, legendLines.join("   "));

    dialog.add("panel", [0, 0, gridW + PAD, 1]);
    var lo = addLaunchOptions(dialog);
    var bg = dialog.add("group"); bg.alignment = "right";
    var expBtn = bg.add("button", undefined, "Export");
    var canBtn = bg.add("button", undefined, "Cancel");
    expBtn.onClick = function() { dialog.close(1); };
    canBtn.onClick = function() { dialog.close(2); };
    dialog.layout.layout(true); dialog.center();
    if (dialog.show() != 1) return null;

    var assignments = {};
    for (var r = 0; r < rows.length; r++) {
        var selArt = null;
        for (var a = 0; a < cbGrid[r].length; a++) { if (cbGrid[r][a].value) { selArt = artworkNames[a]; break; } }
        if (selArt) {
            var key = rows[r].styleName;
            if (!assignments[key]) assignments[key] = { styleName: rows[r].styleName, styleCode: rows[r].styleCode, frontArtwork: null, backArtwork: null };
            if (rows[r].position == "front") assignments[key].frontArtwork = selArt;
            else                              assignments[key].backArtwork  = selArt;
        }
    }
    var sa = [];
    for (var sn in assignments) { var a2 = assignments[sn]; if (a2.frontArtwork || a2.backArtwork) sa.push(a2); }
    return { styleAssignments: sa, launchUploader: lo.launchCheck.value, autoUpload: lo.autoUploadCheck.value, publishActive: lo.publishActiveCheck.value };
}

// ---- MAIN SCRIPT ----
var mainDoc = app.activeDocument;
var smartLayer = findLayerRecursive(mainDoc, smartObjectLayerName);

if (!smartLayer) {
    alert("Smart Object layer '" + smartObjectLayerName + "' not found.");
} else {

    var styles = [];
    for (var i = 0; i < mainDoc.layers.length; i++) {
        var lyr = mainDoc.layers[i];
        if (lyr.typename == "LayerSet" && lyr.name.indexOf("style_") == 0 && lyr.name != "Backgrounds") styles.push(lyr.name);
    }

    var idEdit = stringIDToTypeID("placedLayerEditContents");

    // =================================================================
    // MATRIX FLOW — PSD has front/back (PFM*/PBM*) shirt layers
    // =================================================================
    if (psdHasFrontBackLayers(mainDoc, styles)) {

        var styleInfos = [];
        for (var s = 0; s < styles.length; s++) {
            var sf = findLayerRecursive(mainDoc, styles[s]);
            var pos = detectStylePositions(sf);
            styleInfos.push({ styleName: styles[s], styleCode: getStyleCodeFromFolder(sf), displayName: getStyleDisplayName(styles[s]), hasFront: pos.hasFront, hasBack: pos.hasBack });
        }

        // Open smart object briefly to get artwork names, then close without saving
        mainDoc.activeLayer = smartLayer;
        executeAction(idEdit, undefined, DialogModes.NO);
        var tmpArtDoc = app.activeDocument;
        var allArtworks = detectArtworks(tmpArtDoc);
        tmpArtDoc.close(SaveOptions.DONOTSAVECHANGES);
        mainDoc = app.activeDocument;
        smartLayer = findLayerRecursive(mainDoc, smartObjectLayerName);

        var matrixResult = showMatrixDialog(styleInfos, allArtworks);

        if (matrixResult && matrixResult.styleAssignments.length > 0) {

            // Build flat task list
            var tasks = [];
            for (var i = 0; i < matrixResult.styleAssignments.length; i++) {
                var sa = matrixResult.styleAssignments[i];
                if (sa.frontArtwork) tasks.push({ artwork: sa.frontArtwork, position: "front", styleName: sa.styleName, styleCode: sa.styleCode });
                if (sa.backArtwork)  tasks.push({ artwork: sa.backArtwork,  position: "back",  styleName: sa.styleName, styleCode: sa.styleCode });
            }

            // Unique artworks to iterate over
            var artSeen = {}, uniqueArts = [];
            for (var t = 0; t < tasks.length; t++) {
                if (!artSeen[tasks[t].artwork]) { artSeen[tasks[t].artwork] = true; uniqueArts.push(tasks[t].artwork); }
            }

            // Open smart object for the first iteration
            mainDoc.activeLayer = smartLayer;
            executeAction(idEdit, undefined, DialogModes.NO);
            var artDoc = app.activeDocument;

            for (var ui = 0; ui < uniqueArts.length; ui++) {
                var artName = uniqueArts[ui];

                // Show only this artwork
                for (var ai = 0; ai < artDoc.layers.length; ai++) artDoc.layers[ai].visible = (artDoc.layers[ai].name == artName);
                artDoc.save(); artDoc.close();
                mainDoc = app.activeDocument;
                smartLayer = findLayerRecursive(mainDoc, smartObjectLayerName);
                if (smartLayer) smartLayer.visible = true;

                for (var t = 0; t < tasks.length; t++) {
                    var task = tasks[t];
                    if (task.artwork != artName) continue;

                    var colourPrefix = (task.position == "front") ? "PFM" : "PBM";
                    var styleFolder  = findLayerRecursive(mainDoc, task.styleName);

                    // Show only this style
                    for (var ss = 0; ss < styles.length; ss++) {
                        var sl = findLayerRecursive(mainDoc, styles[ss]);
                        if (sl) setVisibilityRecursive(sl, styles[ss] == task.styleName);
                    }

                    var styleColours = detectFoldersRecursive(styleFolder, "Colour_");
                    for (var c = 0; c < styleColours.length; c++) {
                        for (var cc = 0; cc < styleColours.length; cc++) {
                            var cl = findLayerRecursive(styleFolder, styleColours[cc]);
                            if (cl) setVisibilityRecursive(cl, cc == c);
                        }
                        var colourFolder = findLayerRecursive(styleFolder, styleColours[c]);

                        // Find shirt layer matching position prefix
                        var shirtLyr = null;
                        for (var sl2 = 0; sl2 < colourFolder.layers.length; sl2++) {
                            var l2 = colourFolder.layers[sl2];
                            if (l2.typename != "LayerSet" && l2.name.indexOf(colourPrefix) == 0) { shirtLyr = l2; break; }
                        }
                        if (!shirtLyr) continue;

                        // Show only this shirt layer
                        for (var sl3 = 0; sl3 < colourFolder.layers.length; sl3++) {
                            var l3 = colourFolder.layers[sl3];
                            if (l3.typename != "LayerSet") l3.visible = (l3 === shirtLyr);
                        }

                        exportFlattenedPNG(artName + "_" + shirtLyr.name);
                    }
                }

                // Re-open smart object for next artwork
                mainDoc.activeLayer = smartLayer;
                executeAction(idEdit, undefined, DialogModes.NO);
                artDoc = app.activeDocument;
            }

            // Write pairings.json
            var pdata = { pairings: [] };
            for (var i = 0; i < matrixResult.styleAssignments.length; i++) {
                var sa2 = matrixResult.styleAssignments[i];
                pdata.pairings.push({ style_code: sa2.styleCode, front_artwork: sa2.frontArtwork, back_artwork: sa2.backArtwork });
            }
            var pf = new File(exportFolder + "/pairings.json");
            pf.open("w"); pf.write(JSON.stringify(pdata, null, 2)); pf.close();

            if (matrixResult.launchUploader) launchUploaderWithFolder(exportFolder.fsName, matrixResult.autoUpload, matrixResult.publishActive);
        }

    // =================================================================
    // SIMPLE FLOW — original single-position PSD (backward compatible)
    // =================================================================
    } else {

        var dialogResult = showStyleSelectionDialog(styles);
        if (dialogResult && dialogResult.styles && dialogResult.styles.length > 0) {
            var selectedStyles = dialogResult.styles;
            var launchUploader = dialogResult.launchUploader;
            var autoUpload     = dialogResult.autoUpload;
            var publishActive  = dialogResult.publishActive;

            mainDoc.activeLayer = smartLayer;
            executeAction(idEdit, undefined, DialogModes.NO);
            var artworkDoc = app.activeDocument;
            var artworks   = detectArtworks(artworkDoc);

            for (var a = 0; a < artworks.length; a++) {
                for (var i = 0; i < artworkDoc.layers.length; i++) artworkDoc.layers[i].visible = (artworkDoc.layers[i].name == artworks[a]);
                artworkDoc.save(); artworkDoc.close();
                mainDoc = app.activeDocument;
                smartLayer = findLayerRecursive(mainDoc, smartObjectLayerName);
                if (smartLayer) smartLayer.visible = true;

                for (var s = 0; s < selectedStyles.length; s++) {
                    var styleName = selectedStyles[s];
                    for (var ss = 0; ss < styles.length; ss++) {
                        var styleLayer = mainDoc.layers.getByName(styles[ss]);
                        setVisibilityRecursive(styleLayer, styles[ss] == styleName);
                    }
                    var styleFolder  = mainDoc.layers.getByName(styleName);
                    var styleColours = detectFoldersRecursive(styleFolder, "Colour_");
                    for (var c = 0; c < styleColours.length; c++) {
                        for (var cc = 0; cc < styleColours.length; cc++) {
                            var colLayer = findLayerRecursive(styleFolder, styleColours[cc]);
                            if (colLayer) setVisibilityRecursive(colLayer, styleColours[cc] == styleColours[c]);
                        }
                        var colourFolder = findLayerRecursive(styleFolder, styleColours[c]);
                        var shirtLayerName = "";
                        for (var sl = 0; sl < colourFolder.layers.length; sl++) {
                            var lyr = colourFolder.layers[sl];
                            if (lyr.typename != "LayerSet") { shirtLayerName = lyr.name; break; }
                        }
                        exportFlattenedPNG(artworks[a] + "_" + shirtLayerName);
                    }
                }

                mainDoc.activeLayer = smartLayer;
                executeAction(idEdit, undefined, DialogModes.NO);
                artworkDoc = app.activeDocument;
            }

            if (launchUploader) launchUploaderWithFolder(exportFolder.fsName, autoUpload, publishActive);
        }
    }
}

} // end exportFolder check


// ---- CONFIG ----
var exportFolder = Folder.selectDialog("Choose export folder");
var smartObjectLayerName = "Artworks";
var excludeArtworks = ["DTG Printable Area Frame"];

// ---- HELPERS ----
function isExcluded(name, list) {
    for (var i = 0; i < list.length; i++) {
        if (list[i] == name) return true;
    }
    return false;
}

function findLayerRecursive(parent, name) {
    for (var i = 0; i < parent.layers.length; i++) {
        var layer = parent.layers[i];
        if (layer.name == name) return layer;
        if (layer.typename == "LayerSet") {
            var found = findLayerRecursive(layer, name);
            if (found) return found;
        }
    }
    return null;
}

function setVisibilityRecursive(layer, visible) {
    layer.visible = visible;
    if (layer.typename == "LayerSet") {
        for (var i = 0; i < layer.layers.length; i++) {
            setVisibilityRecursive(layer.layers[i], visible);
        }
    }
}

function detectFoldersRecursive(parent, prefix) {
    var results = [];
    for (var i = 0; i < parent.layers.length; i++) {
        var lyr = parent.layers[i];
        if (lyr.typename == "LayerSet") {
            if (lyr.name.indexOf(prefix) == 0) {
                results.push(lyr.name);
            }
            var sub = detectFoldersRecursive(lyr, prefix);
            for (var j = 0; j < sub.length; j++) {
                results.push(sub[j]);
            }
        }
    }
    return results;
}

function detectArtworks(doc) {
    var arr = [];
    for (var i = 0; i < doc.layers.length; i++) {
        var lyr = doc.layers[i];
        if (!isExcluded(lyr.name, excludeArtworks)) {
            arr.push(lyr.name);
        }
    }
    return arr;
}

function showStyleSelectionDialog(styleNames) {
    var dialog = new Window("dialog", "Select styles to export", [100, 100, 420, 390]);
    dialog.orientation = "column";
    dialog.alignChildren = "left";
    dialog.margins = 16;

    dialog.add("statictext", undefined, "Choose which styles to process:");

    var stylesPanel = dialog.add("panel", undefined, "Styles");
    stylesPanel.orientation = "column";
    stylesPanel.alignChildren = "left";
    stylesPanel.margins = 12;
    stylesPanel.alignment = ["fill", "top"];
    stylesPanel.minimumSize = [340, Math.max(120, styleNames.length * 26 + 20)];

    var checkboxes = [];
    for (var i = 0; i < styleNames.length; i++) {
        var checkbox = stylesPanel.add("checkbox", undefined, styleNames[i]);
        checkbox.value = true;
        checkboxes.push(checkbox);
    }

    // ---- Launch uploader option ----
    var launchCheck = dialog.add("checkbox", undefined, "Launch Moonbeam Uploader when export completes");
    launchCheck.value = false;

    var autoUploadCheck = dialog.add("checkbox", undefined, "    \u2514 Auto-upload immediately on launch");
    autoUploadCheck.value = false;
    autoUploadCheck.enabled = false;

    var publishActiveCheck = dialog.add("checkbox", undefined, "        \u2514 Publish as Active");
    publishActiveCheck.value = false;
    publishActiveCheck.enabled = false;

    launchCheck.onClick = function() {
        autoUploadCheck.enabled = launchCheck.value;
        if (!launchCheck.value) {
            autoUploadCheck.value = false;
            publishActiveCheck.value = false;
            publishActiveCheck.enabled = false;
        }
    };

    autoUploadCheck.onClick = function() {
        publishActiveCheck.enabled = autoUploadCheck.value;
        if (!autoUploadCheck.value) publishActiveCheck.value = false;
    };

    var buttonGroup = dialog.add("group");
    buttonGroup.alignment = "right";
    var okButton = buttonGroup.add("button", undefined, "OK");
    var cancelButton = buttonGroup.add("button", undefined, "Cancel");

    okButton.onClick = function() {
        dialog.close(1);
    };
    cancelButton.onClick = function() {
        dialog.close(2);
    };

    dialog.onShow = function() {
        dialog.layout.layout(true);
        dialog.layout.resize();
    };

    dialog.layout.layout(true);
    dialog.layout.resize();
    dialog.center();
    var result = dialog.show();
    if (result != 1) return null;

    var selectedStyles = [];
    for (var i = 0; i < checkboxes.length; i++) {
        if (checkboxes[i].value) selectedStyles.push(styleNames[i]);
    }
    return { styles: selectedStyles, launchUploader: launchCheck.value, autoUpload: autoUploadCheck.value, publishActive: publishActiveCheck.value };
}

function exportFlattenedPNG(filename) {
    var dup = app.activeDocument.duplicate();
    var file = new File(exportFolder + "/" + filename + ".png");

    // Export PNG-24 without flattening so transparency is preserved.
    var opts = new ExportOptionsSaveForWeb();
    opts.format = SaveDocumentType.PNG;
    opts.PNG8 = false;
    opts.transparency = true;
    opts.interlaced = false;
    opts.includeProfile = false;

    dup.exportDocument(file, ExportType.SAVEFORWEB, opts);
    dup.close(SaveOptions.DONOTSAVECHANGES);
}

// ---- MAIN SCRIPT ----
var mainDoc = app.activeDocument;
var smartLayer = findLayerRecursive(mainDoc, smartObjectLayerName);

if (!smartLayer) {
    alert("Smart Object layer '" + smartObjectLayerName + "' not found.");
} else {

    // ---- Detect styles ONLY at top level ----
    var styles = [];
    for (var i = 0; i < mainDoc.layers.length; i++) {
        var lyr = mainDoc.layers[i];
        if (lyr.typename == "LayerSet" &&
            lyr.name.indexOf("style_") == 0 &&
            lyr.name != "Backgrounds") {
            styles.push(lyr.name);
        }
    }

    var dialogResult = showStyleSelectionDialog(styles);
    if (!dialogResult || !dialogResult.styles || dialogResult.styles.length == 0) {
        alert("No styles selected. Export cancelled.");
    } else {
    var selectedStyles = dialogResult.styles;
    var launchUploader = dialogResult.launchUploader;
    var autoUpload = dialogResult.autoUpload;
    var publishActive = dialogResult.publishActive;

    // Open Smart Object once
    mainDoc.activeLayer = smartLayer;
    var idEdit = stringIDToTypeID("placedLayerEditContents");
    executeAction(idEdit, undefined, DialogModes.NO);

    var artworkDoc = app.activeDocument;
    var artworks = detectArtworks(artworkDoc);

    for (var a = 0; a < artworks.length; a++) {

        // Toggle artwork inside Smart Object
        for (var i = 0; i < artworkDoc.layers.length; i++) {
            artworkDoc.layers[i].visible = (artworkDoc.layers[i].name == artworks[a]);
        }

        artworkDoc.save();
        artworkDoc.close();

        mainDoc = app.activeDocument;

        // Ensure Artworks layer is visible
        smartLayer = findLayerRecursive(mainDoc, smartObjectLayerName);
        if (smartLayer) smartLayer.visible = true;

        for (var s = 0; s < selectedStyles.length; s++) {
            var styleName = selectedStyles[s];

            // Toggle only the selected style
            for (var ss = 0; ss < styles.length; ss++) {
                var styleLayer = mainDoc.layers.getByName(styles[ss]);
                setVisibilityRecursive(styleLayer, styles[ss] == styleName);
            }

            // Colours inside this style
            var styleFolder = mainDoc.layers.getByName(styleName);
            var styleColours = detectFoldersRecursive(styleFolder, "Colour_");

            for (var c = 0; c < styleColours.length; c++) {

                // Toggle only selected colour inside THIS style
                for (var cc = 0; cc < styleColours.length; cc++) {
                    var colLayer = findLayerRecursive(styleFolder, styleColours[cc]);
                    if (colLayer) setVisibilityRecursive(colLayer, styleColours[cc] == styleColours[c]);
                }

                // ---- NEW: extract shirt layer name ----
                var colourFolder = findLayerRecursive(styleFolder, styleColours[c]);
                var shirtLayerName = "";

                for (var sl = 0; sl < colourFolder.layers.length; sl++) {
                    var lyr = colourFolder.layers[sl];
                    if (lyr.typename != "LayerSet") {
                        shirtLayerName = lyr.name;
                        break;
                    }
                }

                // ---- NEW: filename format ----
                var filename = artworks[a] + "_" + shirtLayerName;

                exportFlattenedPNG(filename);
            }
        }

        // Re-open Smart Object for next artwork
        mainDoc.activeLayer = smartLayer;
        executeAction(idEdit, undefined, DialogModes.NO);
        artworkDoc = app.activeDocument;
    }

    // Launch Moonbeam Uploader if the option was ticked
    if (launchUploader) {
        var folderPath = exportFolder.fsName;
        var isWindows = ($.os.toLowerCase().indexOf("windows") >= 0);
        if (isWindows) {
            // Write folder path to a handoff file, then launch
            var handoff = new File("C:/Program Files/Moonbeam-Uploader/.launch_folder");
            handoff.open("w");
            handoff.write(folderPath);
            if (autoUpload) handoff.write("\nauto_upload=true");
            if (publishActive) handoff.write("\npublish_active=true");
            handoff.close();
            app.system('start "" "C:\\Program Files\\Moonbeam-Uploader\\run_gui_windows.bat"');
        } else {
            // Write folder path to a handoff file, then launch
            var handoff = new File("/Applications/Moonbeam-Uploader/.launch_folder");
            handoff.open("w");
            handoff.write(folderPath);
            if (autoUpload) handoff.write("\nauto_upload=true");
            if (publishActive) handoff.write("\npublish_active=true");
            handoff.close();
            app.system('open "/Applications/Moonbeam-Uploader/run_gui_mac.command"');
        }
    }
    }
}
