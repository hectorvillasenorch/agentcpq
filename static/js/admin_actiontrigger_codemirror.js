document.addEventListener("DOMContentLoaded", function () {
  if (typeof CodeMirror === "undefined") {
    return;
  }

  function enhance(id, rows) {
    var textarea = document.getElementById(id);
    if (!textarea) return;
    CodeMirror.fromTextArea(textarea, {
      mode: { name: "javascript", json: true },
      lineNumbers: true,
      indentUnit: 2,
      tabSize: 2,
      theme: "idea",
      viewportMargin: Infinity,
      extraKeys: {
        Tab: function (cm) {
          if (cm.somethingSelected()) {
            cm.indentSelection("add");
          } else {
            cm.replaceSelection("  ", "end");
          }
        },
      },
    });
    // add padding via CodeMirror wrapper
    var wrapper = textarea.nextElementSibling;
    if (wrapper && wrapper.classList.contains("CodeMirror")) {
      wrapper.style.padding = "3em";
    }
  }

  enhance("id_event_type", 10);
  enhance("id_conditions", 12);
  enhance("id_actions", 14);
});
