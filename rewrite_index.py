import os

html_content = """<!DOCTYPE html>
<html>
<head>
    <title>VSF Real-Time Dashboard</title>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
    <style>
        body { margin: 0; padding: 0; display: flex; height: 100vh; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; overflow: hidden; background: #0f0f13; color: #ecf0f1; }
        #data-viewer-container { flex: 0 0 50%; display: flex; flex-direction: column; background: #1a1a24; border-right: 1px solid #2c2c3a; }
        
        #resizer {
            width: 6px;
            background-color: #2c2c3a;
            cursor: col-resize;
            display: flex;
            align-items: center;
            justify-content: center;
            z-index: 1000;
        }
        #resizer:hover, #resizer:active { background-color: #3498db; }
        
        #map-container { flex: 1; position: relative; display: flex; flex-direction: column; }
        #map { width: 100%; flex: 1; }
        
        .header { background: #13131a; color: white; padding: 12px 15px; font-weight: 600; font-size: 14px; display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #2c2c3a; }
        .status-dot { height: 10px; width: 10px; background-color: #2ecc71; border-radius: 50%; display: inline-block; margin-right: 5px; box-shadow: 0 0 8px #2ecc71; }
        
        .btn { background: #2c2c3a; color: #ecf0f1; border: 1px solid #444455; padding: 6px 12px; cursor: pointer; border-radius: 4px; font-size: 12px; font-weight: 500; transition: all 0.2s; }
        .btn:hover { background: #3a3a4d; border-color: #555566; }
        .btn-primary { background: #2980b9; border-color: #3498db; }
        .btn-primary:hover { background: #3498db; }
        .btn-success { background: #27ae60; border-color: #2ecc71; }
        .btn-success:hover { background: #2ecc71; }
        
        .tabs { display: flex; gap: 8px; margin-right: 10px; }
        .tab { padding: 6px 12px; background: #2c2c3a; border: 1px solid #444455; border-radius: 4px; cursor: pointer; font-size: 12px; font-weight: 600; color: #bdc3c7; transition: all 0.2s; }
        .tab:hover { background: #3a3a4d; color: white; }
        .tab.active { background: #3498db; border-color: #2980b9; color: white; }
        
        #table-wrapper { flex: 1; overflow: auto; padding: 0; }
        table { width: 100%; border-collapse: collapse; font-size: 12px; }
        th, td { padding: 8px 12px; text-align: left; border-bottom: 1px solid #2c2c3a; white-space: nowrap; max-width: 300px; overflow: hidden; text-overflow: ellipsis; }
        th { background: #1f1f2e; color: #bdc3c7; font-weight: 600; position: sticky; top: 0; box-shadow: 0 1px 0 #2c2c3a; z-index: 10; }
        tr:hover td { background: #2c2c3a; cursor: pointer; }
        tr.highlighted td { background: #34495e; }
        
        .pagination { display: flex; justify-content: space-between; align-items: center; padding: 10px 15px; background: #13131a; border-top: 1px solid #2c2c3a; font-size: 13px; color: #bdc3c7; }
        
        input[type="text"] { background: #1f1f2e; border: 1px solid #444455; color: white; padding: 6px 10px; border-radius: 4px; font-size: 12px; outline: none; }
        input[type="text"]:focus { border-color: #3498db; }
        
        /* Scrollbar */
        ::-webkit-scrollbar { width: 8px; height: 8px; }
        ::-webkit-scrollbar-track { background: #13131a; }
        ::-webkit-scrollbar-thumb { background: #444455; border-radius: 4px; }
        ::-webkit-scrollbar-thumb:hover { background: #555566; }
    </style>
</head>
<body>
    
    <div id="data-viewer-container">
        <div class="header">
            <span style="display:flex; align-items:center; gap:10px;">
                💾 Data Viewer
                <div class="tabs">
                    <button class="tab active" onclick="setTable('attractions')">Attractions</button>
                    <button class="tab" onclick="setTable('hotels')">Hotels</button>
                    <button class="tab" onclick="setTable('destinations')">Destinations</button>
                </div>
            </span>
            <div style="display: flex; gap: 8px;">
                <input type="text" id="id-search" placeholder="Search by ID..." style="width: 120px;" onkeydown="if(event.key==='Enter') searchId()">
                <button class="btn btn-primary" onclick="searchId()">Find</button>
                <button class="btn" onclick="clearTableSearch()">Clear</button>
            </div>
        </div>
        
        <div id="table-wrapper">
            <table id="data-table">
                <thead id="data-thead"><tr><th>Loading...</th></tr></thead>
                <tbody id="data-tbody"></tbody>
            </table>
        </div>
        
        <div class="pagination">
            <span id="page-info">Showing 0 rows</span>
            <div style="display:flex; gap:8px;">
                <button class="btn" onclick="changePage(-1)" id="btn-prev">Previous</button>
                <button class="btn" onclick="changePage(1)" id="btn-next">Next</button>
            </div>
        </div>
    </div>

    <div id="resizer"></div>

    <div id="map-container">
        <div class="header">
            <span>🗺️ Live Map Viewer</span>
            <div style="display: flex; gap: 10px; align-items: center;">
                <input type="text" id="semantic-search" placeholder="Semantic search attractions..." style="width: 200px;">
                <button onclick="performSearch()" class="btn btn-primary">Search</button>
                <button onclick="clearSearch()" class="btn">Clear</button>
                <span style="margin-left: 10px;"><span class="status-dot"></span> Live Sync</span>
            </div>
        </div>
        <div id="search-results-panel" style="display: none; position: absolute; top: 55px; left: 15px; width: 280px; max-height: calc(100% - 70px); background: #1a1a24; border: 1px solid #444455; z-index: 1000; box-shadow: 0 4px 15px rgba(0,0,0,0.5); border-radius: 6px; overflow-y: auto; flex-direction: column;">
            <div style="padding: 12px; background: #2980b9; color: white; font-weight: 600; font-size: 13px; position: sticky; top: 0; z-index: 2;">Search Results</div>
            <div id="search-results-list" style="padding: 10px; display: flex; flex-direction: column; gap: 8px;"></div>
        </div>
        <div id="map"></div>
    </div>

    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
    <script>
        // === MAP LOGIC ===
        var map = L.map('map').setView([12.245, 109.194], 13);
        
        L.tileLayer('https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png', {
            maxZoom: 19,
            attribution: '&copy; CartoDB'
        }).addTo(map);
        
        var currentMarkers = {};
        let filteredIds = null;

        async function performSearch() {
            const query = document.getElementById('semantic-search').value;
            if (!query) { clearSearch(); return; }
            try {
                const response = await fetch(`http://localhost:8000/api/v1/search_attractions?q=${encodeURIComponent(query)}`);
                const result = await response.json();
                if (result.status === 'success') {
                    window.orderedFilteredIds = result.results.map(r => r.id);
                    window.searchScores = {};
                    result.results.forEach(r => window.searchScores[r.id] = r.score);
                    filteredIds = new Set(window.orderedFilteredIds);
                    fetchLocations();
                }
            } catch(e) {
                console.error("Semantic search failed", e);
                alert("Search failed. Ensure main backend is running on port 8000.");
            }
        }
        
        function clearSearch() {
            document.getElementById('semantic-search').value = '';
            filteredIds = null;
            document.getElementById('search-results-panel').style.display = 'none';
            fetchLocations();
        }

        // Expose focusMap globally so table rows can click to map
        window.focusMap = function(lat, lng, globalId) {
            map.setView([lat, lng], 16);
            if (currentMarkers[globalId]) {
                currentMarkers[globalId].openPopup();
            }
        };

        async function fetchLocations() {
            try {
                const response = await fetch('/api/locations');
                const result = await response.json();
                
                if (result.status === 'success') {
                    let locations = result.data;
                    
                    if (filteredIds) {
                        locations = locations.filter(loc => loc.type !== 'attraction' || filteredIds.has(loc.id));
                        const listContainer = document.getElementById('search-results-list');
                        listContainer.innerHTML = '';
                        if (window.orderedFilteredIds) {
                            window.orderedFilteredIds.forEach(id => {
                                const loc = locations.find(l => l.type === 'attraction' && l.id === id);
                                if (loc) {
                                    const score = window.searchScores[id];
                                    const scorePercent = score ? Math.round(score * 100) + '%' : '';
                                    const item = document.createElement('div');
                                    item.style.cssText = 'padding: 10px; border: 1px solid #2c2c3a; border-radius: 4px; cursor: pointer; font-size: 13px; display: flex; flex-direction: column; background: #1f1f2e; color:#ecf0f1; transition:all 0.2s;';
                                    item.innerHTML = `<div style="display:flex; justify-content:space-between; align-items:center;"><b>${loc.name}</b> <span style="background:#2ecc7122; color:#2ecc71; padding:2px 8px; border-radius:12px; font-size:11px; font-weight:bold;">${scorePercent}</span></div><span style="color:#bdc3c7;font-size:11px;margin-top:5px;">${loc.category}</span>`;
                                    item.onmouseover = () => item.style.background = '#2c2c3a';
                                    item.onmouseout = () => item.style.background = '#1f1f2e';
                                    item.onclick = () => window.focusMap(loc.lat, loc.lng, loc.type + '-' + loc.id);
                                    listContainer.appendChild(item);
                                }
                            });
                        }
                        document.getElementById('search-results-panel').style.display = 'flex';
                    }
                    
                    const newIds = new Set(locations.map(loc => loc.type + '-' + loc.id));
                    for (let globalId in currentMarkers) {
                        if (!newIds.has(globalId)) {
                            map.removeLayer(currentMarkers[globalId]);
                            delete currentMarkers[globalId];
                        }
                    }
                    
                    locations.forEach(loc => {
                        const globalId = loc.type + '-' + loc.id;
                        let popupContent = "";
                        if (loc.type === 'destination') {
                            popupContent = "📍 <b>" + loc.name + "</b><br>Region: " + loc.category;
                        } else if (loc.type === 'hotel') {
                            popupContent = "🏨 <b>" + loc.name + "</b><br>Rating: " + loc.category;
                            if (loc.source_urls && loc.source_urls.length > 0) {
                                popupContent += `<br><a href="${loc.source_urls[0]}" target="_blank" style="display:inline-block; margin-top:5px; margin-bottom:5px; padding:4px 8px; background:#3498db; color:white; text-decoration:none; border-radius:3px; font-size:12px;">🔗 View Source</a>`;
                            }
                        } else {
                            popupContent = "<b>" + loc.name + "</b><br>" + loc.category;
                        }
                        
                        popupContent += `<br><button onclick="window.focusTable('${loc.type}', '${loc.id}')" style="margin-top:8px; padding:6px 10px; background:#2ecc71; color:white; border:none; border-radius:4px; font-size:12px; font-weight:bold; cursor:pointer; width:100%;">🔍 Find in Data Viewer</button>`;
                        
                        if (loc.images && loc.images.length > 0) {
                            popupContent += `<br><img src="${loc.images[0]}" referrerpolicy="no-referrer" loading="lazy" style="width:100%; max-height:150px; margin-top:8px; border-radius:6px; box-shadow:0 2px 5px rgba(0,0,0,0.2);">`;
                        }

                        if (currentMarkers[globalId]) {
                            const existingPos = currentMarkers[globalId].getLatLng();
                            if (existingPos.lat !== loc.lat || existingPos.lng !== loc.lng) {
                                currentMarkers[globalId].setLatLng([loc.lat, loc.lng]);
                            }
                            if (currentMarkers[globalId].customPopupContent !== popupContent) {
                                currentMarkers[globalId].bindPopup(popupContent);
                                currentMarkers[globalId].customPopupContent = popupContent;
                            }
                        } else {
                            let marker;
                            if (loc.type === 'destination') {
                                marker = L.circleMarker([loc.lat, loc.lng], { radius: 10, fillColor: "#e74c3c", color: "#fff", weight: 2, opacity: 1, fillOpacity: 0.9 }).addTo(map);
                            } else if (loc.type === 'hotel') {
                                const hotelIcon = L.divIcon({ html: '<div style="background-color: #f39c12; width: 14px; height: 14px; border-radius: 3px; border: 2px solid white; box-shadow: 0 2px 4px rgba(0,0,0,0.3);"></div>', className: '', iconSize: [18, 18], iconAnchor: [9, 9], popupAnchor: [0, -9] });
                                marker = L.marker([loc.lat, loc.lng], {icon: hotelIcon}).addTo(map);
                            } else {
                                marker = L.marker([loc.lat, loc.lng]).addTo(map);
                            }
                            
                            marker.bindPopup(popupContent, {className: 'custom-popup'});
                            marker.customPopupContent = popupContent;
                            
                            marker.on('dblclick', function() {
                                window.focusTable(loc.type, loc.id);
                            });

                            currentMarkers[globalId] = marker;
                        }
                    });
                }
            } catch (err) {
                console.error("Failed to sync map:", err);
            }
        }

        fetchLocations();
        setInterval(fetchLocations, 60000);


        // === DATA VIEWER LOGIC ===
        let currentTable = 'attractions';
        let currentPage = 1;
        const pageSize = 100;
        let currentSearchId = null;

        function setTable(tableName) {
            currentTable = tableName;
            currentPage = 1;
            currentSearchId = null;
            document.getElementById('id-search').value = '';
            
            document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
            event.target.classList.add('active');
            
            loadTableData();
        }

        async function loadTableData() {
            const thead = document.getElementById('data-thead');
            const tbody = document.getElementById('data-tbody');
            const info = document.getElementById('page-info');
            const btnPrev = document.getElementById('btn-prev');
            const btnNext = document.getElementById('btn-next');
            
            tbody.innerHTML = '<tr><td colspan="100" style="text-align:center; padding: 20px; color:#bdc3c7;">Loading data...</td></tr>';
            
            let url = `/api/data/${currentTable}?page=${currentPage}&page_size=${pageSize}`;
            if (currentSearchId) {
                url += `&item_id=${encodeURIComponent(currentSearchId)}`;
            }

            try {
                const res = await fetch(url);
                const result = await res.json();
                
                if (result.status !== 'success') {
                    tbody.innerHTML = `<tr><td colspan="100" style="color:#e74c3c; padding:20px;">Error: ${result.message}</td></tr>`;
                    return;
                }
                
                const data = result.data;
                const totalCount = result.count;
                
                if (data.length === 0) {
                    tbody.innerHTML = '<tr><td colspan="100" style="text-align:center; padding: 20px; color:#bdc3c7;">No records found.</td></tr>';
                    thead.innerHTML = '';
                    info.textContent = `Showing 0 rows`;
                    btnPrev.disabled = true;
                    btnNext.disabled = true;
                    return;
                }
                
                // Build headers based on the first row keys
                const keys = Object.keys(data[0]);
                thead.innerHTML = '<tr>' + keys.map(k => `<th>${k}</th>`).join('') + '</tr>';
                
                // Build rows
                tbody.innerHTML = data.map(row => {
                    let lat = null, lng = null;
                    if (row.coordinates) {
                        const parts = row.coordinates.split(',');
                        if (parts.length === 2) { lat = parts[0]; lng = parts[1]; }
                    }
                    const tr = document.createElement('tr');
                    if (currentSearchId === row.id) tr.classList.add('highlighted');
                    
                    if (lat && lng) {
                        tr.onclick = () => window.focusMap(lat, lng, (currentTable === 'attractions' ? 'attraction' : (currentTable === 'hotels' ? 'hotel' : 'destination')) + '-' + row.id);
                    }
                    
                    const tds = keys.map(k => {
                        let val = row[k];
                        if (val === null || val === undefined) val = '';
                        if (typeof val === 'object') val = JSON.stringify(val);
                        // Make links clickable
                        if (typeof val === 'string' && val.startsWith('http')) {
                            val = `<a href="${val}" target="_blank" style="color:#3498db;text-decoration:none;">Link</a>`;
                        }
                        return `<td>${val}</td>`;
                    }).join('');
                    
                    return `<tr ${lat ? `onclick="window.focusMap(${lat}, ${lng}, '${currentTable.slice(0,-1)}-${row.id}')"` : ''} class="${currentSearchId == row.id ? 'highlighted' : ''}">${tds}</tr>`;
                }).join('');
                
                // Pagination state
                const start = (currentPage - 1) * pageSize + 1;
                const end = Math.min(currentPage * pageSize, totalCount);
                info.textContent = currentSearchId ? `Found 1 result` : `Showing ${start} - ${end} of ${totalCount}`;
                
                btnPrev.disabled = currentPage === 1;
                btnNext.disabled = end >= totalCount;
                
            } catch(e) {
                tbody.innerHTML = `<tr><td colspan="100" style="color:#e74c3c; padding:20px;">Connection failed.</td></tr>`;
            }
        }

        function changePage(delta) {
            currentPage += delta;
            if (currentPage < 1) currentPage = 1;
            loadTableData();
        }

        function searchId() {
            const val = document.getElementById('id-search').value.trim();
            if (val) {
                currentSearchId = val;
                currentPage = 1;
                loadTableData();
            }
        }

        function clearTableSearch() {
            document.getElementById('id-search').value = '';
            currentSearchId = null;
            currentPage = 1;
            loadTableData();
        }

        // Exposed for map popups
        window.focusTable = function(type, id) {
            const tableName = type + 's';
            
            // Switch tab visually
            document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
            const tabs = Array.from(document.querySelectorAll('.tab'));
            const targetTab = tabs.find(t => t.textContent.toLowerCase() === tableName.toLowerCase());
            if (targetTab) targetTab.classList.add('active');
            
            currentTable = tableName;
            document.getElementById('id-search').value = id;
            searchId();
        };

        // Initial table load
        loadTableData();

        // === RESIZER LOGIC ===
        const resizer = document.getElementById('resizer');
        const leftPanel = document.getElementById('data-viewer-container');
        let isResizing = false;

        resizer.addEventListener('mousedown', function(e) {
            isResizing = true;
            document.body.classList.add('resizing-active');
            e.preventDefault();
        });

        document.addEventListener('mousemove', function(e) {
            if (!isResizing) return;
            let newWidth = (e.clientX / window.innerWidth) * 100;
            if (newWidth < 20) newWidth = 20;
            if (newWidth > 80) newWidth = 80;
            leftPanel.style.flex = `0 0 ${newWidth}%`;
            if (map) { map.invalidateSize(); }
        });

        document.addEventListener('mouseup', function(e) {
            if (isResizing) {
                isResizing = false;
                document.body.classList.remove('resizing-active');
                if (map) { map.invalidateSize(); }
            }
        });

    </script>
</body>
</html>"""

with open(r'd:\Git repo\vsf-project\src\airflow\dashboard\templates\index.html', 'w', encoding='utf-8') as f:
    f.write(html_content)
