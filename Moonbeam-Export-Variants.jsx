// =====================================================
//  Photoshop Ultra-Fast Variant Export Script
//  Styles = top-level folders (style_expresser, style_creator, etc.)
//  Colours = Colour_ folders inside each style
//  Filename = ArtworkName_ShirtLayerName.png
// =====================================================

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
    var dialog = new Window("dialog", "Select styles to export", [100, 100, 420, 360]);
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
    if (result != 1) return [];

    var selectedStyles = [];
    for (var i = 0; i < checkboxes.length; i++) {
        if (checkboxes[i].value) selectedStyles.push(styleNames[i]);
    }
    return selectedStyles;
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

    var selectedStyles = showStyleSelectionDialog(styles);
    if (!selectedStyles || selectedStyles.length == 0) {
        alert("No styles selected. Export cancelled.");
    } else {

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

    alert("All artwork + style + colour variants exported!");
    }
}
