-- Diagnostic v2: try EVERY method to write output
-- Method 1: io.open with various paths
local paths = {
  "C:/Users/mehdi/Desktop/Dev/PokemonCoopGBA/_diag_out.txt",
  "C:\\Users\\mehdi\\Desktop\\Dev\\PokemonCoopGBA\\_diag_out.txt",
  "./_diag_out.txt",
  "_diag_out.txt",
}
for _, p in ipairs(paths) do
  local f = io.open(p, "w")
  if f then
    f:write("io.open worked with: " .. p .. "\n")
    f:close()
    break
  end
end

-- Method 2: os.execute to create file
pcall(function()
  os.execute('echo diag2_os_execute > "C:/Users/mehdi/Desktop/Dev/PokemonCoopGBA/_diag_os.txt"')
end)

-- Method 3: print to stdout (might show in terminal)
print("DIAG2: script is running")

-- Method 4: if console exists, log there
pcall(function()
  if console then console:log("DIAG2: console works") end
end)
