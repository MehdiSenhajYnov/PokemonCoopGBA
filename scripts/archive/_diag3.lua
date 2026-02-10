-- Diagnostic v3: ABSOLUTELY ZERO mGBA API calls
-- Just pure Lua to test if scripts execute at all
local f = io.open("C:/Users/mehdi/Desktop/Dev/PokemonCoopGBA/_diag3.txt", "w")
if f then
  f:write("pure_lua_ok\n")
  f:write("os.clock = " .. tostring(os.clock()) .. "\n")
  f:close()
end
