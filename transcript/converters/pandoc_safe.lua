-- Transcript: keep pandoc from copying local files from outside the document's folder into
-- the result. An untrusted document could otherwise point at absolute paths, file: URLs or
-- "../" paths and smuggle private files into a result that is later shared. Images inside
-- the folder, web images and resources embedded in the input itself keep working.

local SAFE_SCHEMES = { http = true, https = true, data = true }
-- Attributes whose value pandoc may fetch (--embed-resources, --extract-media, Office writers).
local URL_ATTRIBUTES = {
  src = true, ["data-src"] = true, srcset = true, href = true, ["xlink:href"] = true,
  poster = true, data = true, background = true,
}
-- Metadata that templates and the EPUB writer turn into files to read.
local FILE_METADATA = { "css", "stylesheet", "cover-image", "epub-cover-image" }

local function percent_decode(s)
  return (s:gsub("%%(%x%x)", function(hex) return string.char(tonumber(hex, 16)) end))
end

local function codepoint(n)
  return n and n >= 0 and n < 0x110000 and utf8.char(n) or "?"
end

-- Named character references that matter in a path or a CSS url().
local ENTITIES = {
  sol = "/", bsol = "\\", colon = ":", period = ".", percnt = "%", quot = '"', apos = "'",
  Tab = "", NewLine = "", amp = "&",
}

-- The value as an HTML parser sees it.
local function html_decode(s)
  s = s:gsub("&#[xX](%x+);?", function(hex) return codepoint(tonumber(hex, 16)) end)
  s = s:gsub("&#(%d+);?", function(dec) return codepoint(tonumber(dec)) end)
  return (s:gsub("&(%a+);?", ENTITIES))
end

-- True when fetching ``target`` could read a file outside the document's folder.
local function unsafe(target)
  target = target:gsub("[%c]", ""):match("^%s*(.-)%s*$")
  local scheme = target:match("^(%a[%w+.-]*):")
  if scheme and #scheme > 1 then -- a one-letter scheme is a Windows drive
    return not SAFE_SCHEMES[scheme:lower()]
  end
  -- pandoc drops the query and fragment and decodes %XX before opening a local file.
  local path = percent_decode((target:gsub("[?#].*", "")))
  if path:match("^[/\\]") or path:match("^%a:") then
    return true
  end
  local depth = 0
  for part in path:gmatch("[^/\\]+") do
    if part == ".." then
      depth = depth - 1
      if depth < 0 then
        return true
      end
    elseif part ~= "." then
      depth = depth + 1
    end
  end
  return false
end

local function unsafe_html(value)
  local decoded = html_decode(value)
  if unsafe(decoded) then
    return true
  end
  for candidate in decoded:gmatch("[^,]+") do -- srcset: "a.png 1x, b.png 2x"
    if unsafe(candidate:match("^%s*(%S*)")) then
      return true
    end
  end
  return false
end

-- CSS url(...) and @import "..." (style attributes and <style> elements).
local function clean_css(css)
  local function check(prefix, quote, target, suffix)
    local decoded = html_decode(target):match("^[%s\"']*(.-)[%s\"']*$") -- url(&quot;...&quot;)
    if decoded:find("\\", 1, true) or unsafe(decoded) then -- CSS escapes could hide a path
      return prefix .. quote .. quote .. (suffix or "")
    end
  end
  css = css:gsub("([uU][rR][lL]%(%s*)([\"']?)(.-)%2(%s*%))", check)
  return (css:gsub("(@[iI][mM][pP][oO][rR][tT]%s*)([\"'])(.-)%2", check))
end

local function clean_html(text)
  local function attribute(name, value)
    if URL_ATTRIBUTES[name:lower()] and unsafe_html(value) then
      return ""
    end
  end
  -- Scanned over the whole text rather than tag by tag, so a ">" inside a value cannot hide anything.
  text = text:gsub('%f[%w:_%-]([%w:_%-]+)%s*=%s*"([^"]*)"', attribute)
  text = text:gsub("%f[%w:_%-]([%w:_%-]+)%s*=%s*'([^']*)'", attribute)
  text = text:gsub("%f[%w:_%-]([%w:_%-]+)%s*=%s*([^%s\"'=<>`]+)", attribute)
  return clean_css(text)
end

local function clean_attributes(el)
  local changes = {}
  for name, value in pairs(el.attributes) do
    local lower = name:lower()
    if URL_ATTRIBUTES[lower] and unsafe_html(value) then
      changes[name] = false
    elseif lower == "style" and clean_css(value) ~= value then
      changes[name] = clean_css(value)
    end
  end
  if next(changes) == nil then
    return nil
  end
  for name, value in pairs(changes) do
    el.attributes[name] = value or nil
  end
  return el
end

local function in_mediabag(src)
  return pandoc.mediabag.lookup(src) ~= nil -- embedded in the input (DOCX, EPUB, notebook...)
end

local filter = {}

function filter.Image(el)
  if not in_mediabag(el.src) and unsafe(el.src) then
    -- A plain link keeps the reference visible without reading the file.
    local text = #el.caption > 0 and el.caption or { pandoc.Str(el.src) }
    return pandoc.Link(text, el.src, el.title)
  end
  return clean_attributes(el)
end

local function raw(el)
  if el.format:match("^html") then
    local text = clean_html(el.text)
    if text ~= el.text then
      el.text = text
      return el
    end
  end
end
filter.RawInline = raw
filter.RawBlock = raw

for _, name in ipairs({ "Div", "Span", "Header", "Link", "Code", "CodeBlock", "Table", "Figure" }) do
  filter[name] = clean_attributes
end

local function unsafe_meta(value)
  local kind = pandoc.utils.type and pandoc.utils.type(value) or type(value) -- pandoc < 2.17
  if kind == "boolean" then
    return false
  elseif kind == "List" or kind == "table" and value.t == "MetaList" then
    for _, item in ipairs(value) do
      if unsafe_meta(item) then
        return true
      end
    end
    return false
  end
  return unsafe(pandoc.utils.stringify(value))
end

function filter.Meta(meta)
  for _, key in ipairs(FILE_METADATA) do
    if meta[key] ~= nil and unsafe_meta(meta[key]) then
      meta[key] = nil
    end
  end
  return meta
end

return { filter }
