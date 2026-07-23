<?php
$_GET["text_length"] = 9999; // Force Adminer to not truncate long strings
class AllowIframe {
    function headers() {
        header_remove("X-Frame-Options");
        header_remove("Content-Security-Policy");
    }

    function credentials() {
        return array('postgres', 'airflow', 'airflow');
    }
    
    function database() {
        return 'vsf_database';
    }
    
    function login($login, $password) {
        return true;
    }

    function head() {
        echo '<script>
        document.addEventListener("DOMContentLoaded", function() {
            // 1. Add Refresh Button
            var btn = document.createElement("button");
            btn.innerText = "🔄 Refresh Table";
            btn.style.position = "fixed";
            btn.style.top = "10px";
            btn.style.right = "10px";
            btn.style.padding = "8px 12px";
            btn.style.background = "#007bff";
            btn.style.color = "white";
            btn.style.border = "none";
            btn.style.borderRadius = "4px";
            btn.style.cursor = "pointer";
            btn.style.zIndex = "9999";
            btn.onclick = function() {
                window.location.href = window.location.href;
            };
            document.body.appendChild(btn);

            // 2. Horizontal Scroll for Table
            var table = document.querySelector("table");
            if (table) {
                var wrapper = document.createElement("div");
                wrapper.style.overflowX = "auto";
                wrapper.style.width = "100%";
                wrapper.style.marginBottom = "20px";
                table.parentNode.insertBefore(wrapper, table);
                wrapper.appendChild(table);

                // 3. Resizable Columns (wrap th content in resizable divs)
                var headers = table.querySelectorAll("th");
                headers.forEach(function(th) {
                    var a = th.querySelector("a");
                    var colName = a ? a.innerText.toLowerCase() : "";
                    var colType = (a && a.getAttribute("title")) ? a.getAttribute("title").toLowerCase() : "";

                    var defaultWidth = "150px";
                    if (!a) {
                        defaultWidth = "60px"; // Action columns
                    } else if (colType.includes("int") || colType.includes("serial") || colType.includes("bool")) {
                        defaultWidth = "80px";
                    } else if (colType.includes("timestamp") || colType.includes("date") || colType.includes("time")) {
                        defaultWidth = "160px";
                    } else if (colType.includes("json") || colType.includes("text") || colName === "images") {
                        defaultWidth = "300px";
                    } else if (colType.includes("varchar") || colType.includes("char")) {
                        defaultWidth = "200px";
                    } else if (colType.includes("float") || colType.includes("double") || colType.includes("numeric") || colType.includes("real")) {
                        defaultWidth = "100px";
                    }

                    var div = document.createElement("div");
                    div.innerHTML = th.innerHTML;
                    div.style.resize = "horizontal";
                    div.style.overflow = "hidden"; // Changed to hidden so scrollbars do not cover the resize handle
                    div.style.minWidth = "40px";
                    // Set width based on data type!
                    div.style.width = defaultWidth;
                    div.style.padding = "2px 6px 12px 2px"; // Extra padding on right/bottom for the handle
                    div.style.boxSizing = "border-box";
                    div.style.borderBottom = "1px dotted #ccc"; // Visual indicator
                    th.innerHTML = "";
                    th.appendChild(div);
                });
            }

            // 4. Map Focusing on click
            var rows = document.querySelectorAll("table tr");
            rows.forEach(function(row) {
                row.style.cursor = "pointer";
                row.addEventListener("click", function(e) {
                    // Let links and checkboxes work normally
                    if (e.target.tagName === "A" || e.target.tagName === "INPUT") {
                        return;
                    }
                    
                    // Stop Adminer default row click behavior
                    e.preventDefault();
                    e.stopPropagation();

                    // Highlight the selected row
                    var allRows = document.querySelectorAll("table tr");
                    allRows.forEach(r => {
                        if (r.style.backgroundColor === "rgb(255, 243, 205)" || r.style.backgroundColor === "#fff3cd") {
                            r.style.backgroundColor = "";
                        }
                    });
                    row.style.backgroundColor = "#fff3cd";

                    var tds = row.querySelectorAll("td");
                    for (var i = 0; i < tds.length; i++) {
                        var text = tds[i].textContent.trim(); // textContent ignores CSS truncation like text-overflow: ellipsis, but needs trimming
                        var match = text.match(/^(-?\d+\.\d+),\s*(-?\d+\.\d+)$/);
                        if (match) {
                            window.parent.postMessage({
                                action: "focus_map",
                                lat: parseFloat(match[1]),
                                lng: parseFloat(match[2])
                            }, "*");
                            break;
                        }
                    }
                }, true);
            });

            // 5. Highlight and focus row from URL hash
            function focusRowFromHash() {
                var hash = window.location.hash;
                if (hash.startsWith("#focus-id-")) {
                    var targetId = hash.substring(10);
                    var rows = document.querySelectorAll("table tr");
                    
                    // Reset all row backgrounds first
                    rows.forEach(r => {
                        if (r.style.backgroundColor === "rgb(255, 243, 205)") {
                            r.style.backgroundColor = "";
                        }
                    });
                    
                    rows.forEach(function(row) {
                        var tds = row.querySelectorAll("td");
                        for (var i = 0; i < tds.length; i++) {
                            if (tds[i].textContent.trim() === targetId) {
                                row.style.backgroundColor = "#fff3cd"; // Highlight with a light yellow
                                row.style.transition = "background-color 0.5s";
                                row.scrollIntoView({behavior: "smooth", block: "center"});
                                break;
                            }
                        }
                    });
                }
            }
            window.addEventListener("hashchange", focusRowFromHash);
            focusRowFromHash(); // Check on initial load
        });
        </script>';
        return false;
    }
}
return new AllowIframe();
?>
