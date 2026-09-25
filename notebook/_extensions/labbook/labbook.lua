-- Shortcodes that take provenance and numbers from the ledgers instead of having them typed by hand.
--   {{< prov R-0007 >}}              -> "Run R-0007, commit abc1234, 2026-09-16"
--   {{< run-param R-0007 chi >}}     -> value of the parameter `chi` of this run
--   {{< result R-0007 dAV >}}        -> latest value of the metric from results.tsv (with unit)
-- `lauf-param` and `ergebnis` are the German names of earlier versions and remain valid.
-- Missing data are marked in bold and visibly, never replaced silently.

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

local function prov(args)
  local id = pandoc.utils.stringify(args[1])
  local d = read_prov(id)
  if not d then return missing("provenance missing: " .. id) end
  local commit = string.sub(d.git.commit or "", 1, 7)
  local dirty = d.git.dirty and " (uncommitted changes)" or ""
  local date = string.sub(d.start or "", 1, 10)
  return pandoc.Emph(pandoc.Str("Run " .. id .. ", commit " .. commit .. dirty .. ", " .. date))
end

local function run_param(args)
  local id = pandoc.utils.stringify(args[1])
  local key = pandoc.utils.stringify(args[2])
  local d = read_prov(id)
  if not d then return missing("provenance missing: " .. id) end
  local v = d.parameter and d.parameter[key]
  if v == nil then return missing("parameter " .. key .. " missing in " .. id) end
  return pandoc.Str(tostring(v))
end

-- results.tsv columns (ledger format): lauf = run, art = kind, metrik = metric, wert = value, einheit = unit
local function result(args)
  local id = pandoc.utils.stringify(args[1])
  local metric = pandoc.utils.stringify(args[2])
  local f = io.open(root() .. "/results.tsv", "r")
  if not f then return missing("results.tsv missing") end
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
  if not value then return missing("result " .. metric .. " missing for " .. id) end
  if unit ~= "" then return pandoc.Str(value .. " " .. unit) end
  return pandoc.Str(value)
end

return {
  ["prov"] = prov,
  ["run-param"] = run_param,
  ["result"] = result,
  ["lauf-param"] = run_param,
  ["ergebnis"] = result,
}
