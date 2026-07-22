<?php
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
                    var div = document.createElement("div");
                    div.innerHTML = th.innerHTML;
                    div.style.resize = "horizontal";
                    div.style.overflow = "auto";
                    div.style.minWidth = "100px";
                    div.style.padding = "2px";
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

                    var tds = row.querySelectorAll("td");
                    for (var i = 0; i < tds.length; i++) {
                        var text = tds[i].innerText;
                        var match = text.match(/^(-?\\d+\\.\\d+),\\s*(-?\\d+\\.\\d+)$/);
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
        });
        </script>';
        return false;
    }
}
return new AllowIframe();
?>
