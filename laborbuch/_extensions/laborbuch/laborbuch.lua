-- Shortcodes, die Provenienz und Zahlen aus den Ledgern holen statt sie abzutippen.
--   {{< prov R-0007 >}}                    -> "Lauf R-0007, Commit abc1234, 2026-09-16"
--   {{< lauf-param R-0007 chi >}}          -> Wert des Parameters `chi` dieses Laufs
--   {{< ergebnis R-0007 dAV >}}            -> letzter Wert der Metrik aus results.tsv (mit Einheit)
-- Fehlende Daten werden fett und sichtbar markiert, nie still ersetzt.

local function root()
  return quarto.project.directory or "."
end

local function missing(msg)
  return pandoc.Strong(pandoc.Str("[" .. msg .. "]"))
end

local function read_prov(id)
  local f = io.open(root() .. "/runs/" .. id .. "/provenance.json", "r")
  if not f then return nil end
  local ok, data = pcall(pandoc.json.decode, f:read("a"))
  f:close()
  if ok then return data end
  return nil
end

local function split_tab(line)
  local out = {}
  for field in (line .. "\t"):gmatch("([^\t]*)\t") do table.insert(out, field) end
  return out
end

return {
  ["prov"] = function(args)
    local id = pandoc.utils.stringify(args[1])
    local d = read_prov(id)
    if not d then return missing("Provenienz fehlt: " .. id) end
    local commit = string.sub(d.git.commit or "", 1, 7)
    local dirty = d.git.dirty and " (uncommittete Änderungen)" or ""
    local date = string.sub(d.start or "", 1, 10)
    return pandoc.Emph(pandoc.Str("Lauf " .. id .. ", Commit " .. commit .. dirty .. ", " .. date))
  end,

  ["lauf-param"] = function(args)
    local id = pandoc.utils.stringify(args[1])
    local key = pandoc.utils.stringify(args[2])
    local d = read_prov(id)
    if not d then return missing("Provenienz fehlt: " .. id) end
    local v = d.parameter and d.parameter[key]
    if v == nil then return missing("Parameter " .. key .. " fehlt in " .. id) end
    return pandoc.Str(tostring(v))
  end,

  ["ergebnis"] = function(args)
    local id = pandoc.utils.stringify(args[1])
    local metric = pandoc.utils.stringify(args[2])
    local f = io.open(root() .. "/results.tsv", "r")
    if not f then return missing("results.tsv fehlt") end
    local header, value, unit = nil, nil, ""
    for line in f:lines() do
      local cols = split_tab(line)
      if not header then
        header = {}
        for i, name in ipairs(cols) do header[name] = i end
      elseif cols[header["art"]] == "ergebnis" and cols[header["lauf"]] == id
             and cols[header["metrik"]] == metric then
        value, unit = cols[header["wert"]], cols[header["einheit"]] or ""
      end
    end
    f:close()
    if not value then return missing("Ergebnis " .. metric .. " fehlt für " .. id) end
    if unit ~= "" then return pandoc.Str(value .. " " .. unit) end
    return pandoc.Str(value)
  end,
}
