-- Minimal IO test
console:log("[TestIO] Script started!")

-- Try multiple paths
local paths = {
  "C:/Users/mehdi/Desktop/Dev/PokemonCoopGBA/test_io_output.txt",
  "test_io_output.txt",
  "C:\\Users\\mehdi\\Desktop\\Dev\\PokemonCoopGBA\\test_io_output.txt",
}

for _, p in ipairs(paths) do
  local ok, err = pcall(function()
    local f = io.open(p, "w")
    if f then
      f:write("IO works! Path: " .. p .. "\n")
      f:close()
      console:log("[TestIO] SUCCESS writing to: " .. p)
    else
      console:log("[TestIO] io.open returned nil for: " .. p)
    end
  end)
  if not ok then
    console:log("[TestIO] pcall error for " .. p .. ": " .. tostring(err))
  end
end

-- Try os.execute
pcall(function()
  os.execute('echo IO_EXEC_WORKS > "C:/Users/mehdi/Desktop/Dev/PokemonCoopGBA/test_exec_output.txt"')
  console:log("[TestIO] os.execute attempted")
end)

-- Try storage API
pcall(function()
  if storage then
    storage:setValue("test_key", "test_value")
    console:log("[TestIO] storage API works")
  else
    console:log("[TestIO] storage API not available")
  end
end)

console:log("[TestIO] Script completed!")
