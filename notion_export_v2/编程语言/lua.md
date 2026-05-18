<details>
<summary>lua里的set不是table.insert啊, 而是table\[xx\] = true</summary>
	 table.insert(MyTable,5)
	像这样插入的数据 不能通过 MyTable\[5\]去判断 ,因为这样是数组在使用 它的下标是1
	要用MyTable\[5\] = true 这样才是当成了set在使用
</details>
<details>
<summary>传参传进去之前非空 传进去后为空  可能是不小心用了.而不是:</summary>
</details>
<details>
<summary>lua中table传参 或 = 赋值都是浅拷贝啊!</summary>
	![](https://prod-files-secure.s3.us-west-2.amazonaws.com/f117ffa6-9d35-4dfc-8a5a-12561e26967c/a4ba9092-58d3-48b4-ac24-780c5c4baddf/image.png?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Content-Sha256=UNSIGNED-PAYLOAD&X-Amz-Credential=ASIAZI2LB466WOOXGWJ5%2F20260422%2Fus-west-2%2Fs3%2Faws4_request&X-Amz-Date=20260422T074013Z&X-Amz-Expires=3600&X-Amz-Security-Token=IQoJb3JpZ2luX2VjEH4aCXVzLXdlc3QtMiJHMEUCIQDGDHb0NegQO9eNtMTwBdrSIPFiTXQAU%2FbOupstu2Wh6gIgdbz0WEwsrM8wLNCpBBPFG06AyOkxDtb3CcjaOHH7Q98q%2FwMIRxAAGgw2Mzc0MjMxODM4MDUiDIOBD4M7v6mPjOBtbSrcA432GaIxsAXU1O6vA4V4hk7yh09%2FYYPuLIQO3WiCix5TbmTykWveRvfMmG1G9ZLcciXLWadEJ3dCcdg9X%2F28MlOGNSFNv%2Ftqa5k%2FVutRwlXBS%2Fdkpd7tGjzr1M%2F82VaLqakfzcOdt38dyt1Njf9c7cP%2BoGO7qZpPR1Q6MvjYd7tfTMzL870z%2FckBzfkkxo%2BV7QYasbBJzRkGnbI2VY1J9Y%2F4hA5gn1MeAmFLc4v4e3xxUkBvBwvK6c7Fycu5hRUD0lSZJ7Xl38hy9iljXuTGyK%2FgAo2XhsbcYu%2BbLqX%2B%2BZruzRTdMnizPAmxw%2BkSfEtwjgVo4ep71vv9RtXe6p0q%2FjhN3vnYqTR07kMdp%2B492keWICOLrBJF%2FBkVqHpOvkkGy1kS4PRFu%2BVwnS5eIDzOdD1CON31tji5xqB5VaxUrFhdJEmJWk74CpB51fluuAJar1ykOFp7%2BPmEiIInHUYaL7Dw093dhB%2Bruy9uZWss1jPR5Qgq0ItmCYRPA05kRNz4A%2Fa4jrsOohO28lpMFEPluDrwqpCUNI9cwbDIFJFURg3LqLYMcLe81UcldTE3FUzdKndnuVLrXv7%2FtScXdo4SXSgOnySZv9Vb%2BTb6prpvYkE0mDhnXQZT4xmPXbZKMMW9oc8GOqUBOQUOqch9gapzQkNoWULTj870VXXJupVRviGYDlYO5EJzU69eF8EhcX%2BwFeXllg%2B303pRYZpUDDLlmIy7IdNhLweAuRLNjrQPQ%2BE1wYDrbmn8HgEY0pgINCxcnf%2BLx3EDAoF%2FIr3AyYxBGa8De890N7IcxRXHIEHoqWaq39yJGdG0Dwy2DRuO7IbaW%2BMiGhmfMBZk59%2FzrRB%2Bh%2FR4y7OXmmWiE3eB&X-Amz-Signature=71c59b140cb6932738095b08d815a648f9199ecf760fa588ec89e8e71b9aa600&X-Amz-SignedHeaders=host&x-amz-checksum-mode=ENABLED&x-id=GetObject)
	所以table的赋值一般都是自己的框架里封装一个clone方法
	参考:[https://blog.csdn.net/fightsyj/article/details/85055342](https://blog.csdn.net/fightsyj/article/details/85055342)
	```lua
function clone( object )
    local lookup_table = {}
    local function copyObj( object )
        if type( object ) ~= "table" then
            return object
        elseif lookup_table[object] then
            return lookup_table[object]
        end
        
        local new_table = {}
        lookup_table[object] = new_table
        for key, value in pairs( object ) do
            new_table[copyObj( key )] = copyObj( value )
        end
        return setmetatable( new_table, getmetatable( object ) )
    end
    return copyObj( object )
end
	```
</details>
<details>
<summary>lua整除运算符//</summary>
	lua中“ **/** ”代表除法，计算结果都是存在小数的。 lua5.3后还提供了一个整除的运算符“ // "<br><br>
</details>
<details>
<summary>vscode luahelper插件 断点调试lua</summary>
	![](https://prod-files-secure.s3.us-west-2.amazonaws.com/f117ffa6-9d35-4dfc-8a5a-12561e26967c/38e1a9d2-2a16-45b6-a43b-b96e3150a0bf/image.png?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Content-Sha256=UNSIGNED-PAYLOAD&X-Amz-Credential=ASIAZI2LB466WOOXGWJ5%2F20260422%2Fus-west-2%2Fs3%2Faws4_request&X-Amz-Date=20260422T074013Z&X-Amz-Expires=3600&X-Amz-Security-Token=IQoJb3JpZ2luX2VjEH4aCXVzLXdlc3QtMiJHMEUCIQDGDHb0NegQO9eNtMTwBdrSIPFiTXQAU%2FbOupstu2Wh6gIgdbz0WEwsrM8wLNCpBBPFG06AyOkxDtb3CcjaOHH7Q98q%2FwMIRxAAGgw2Mzc0MjMxODM4MDUiDIOBD4M7v6mPjOBtbSrcA432GaIxsAXU1O6vA4V4hk7yh09%2FYYPuLIQO3WiCix5TbmTykWveRvfMmG1G9ZLcciXLWadEJ3dCcdg9X%2F28MlOGNSFNv%2Ftqa5k%2FVutRwlXBS%2Fdkpd7tGjzr1M%2F82VaLqakfzcOdt38dyt1Njf9c7cP%2BoGO7qZpPR1Q6MvjYd7tfTMzL870z%2FckBzfkkxo%2BV7QYasbBJzRkGnbI2VY1J9Y%2F4hA5gn1MeAmFLc4v4e3xxUkBvBwvK6c7Fycu5hRUD0lSZJ7Xl38hy9iljXuTGyK%2FgAo2XhsbcYu%2BbLqX%2B%2BZruzRTdMnizPAmxw%2BkSfEtwjgVo4ep71vv9RtXe6p0q%2FjhN3vnYqTR07kMdp%2B492keWICOLrBJF%2FBkVqHpOvkkGy1kS4PRFu%2BVwnS5eIDzOdD1CON31tji5xqB5VaxUrFhdJEmJWk74CpB51fluuAJar1ykOFp7%2BPmEiIInHUYaL7Dw093dhB%2Bruy9uZWss1jPR5Qgq0ItmCYRPA05kRNz4A%2Fa4jrsOohO28lpMFEPluDrwqpCUNI9cwbDIFJFURg3LqLYMcLe81UcldTE3FUzdKndnuVLrXv7%2FtScXdo4SXSgOnySZv9Vb%2BTb6prpvYkE0mDhnXQZT4xmPXbZKMMW9oc8GOqUBOQUOqch9gapzQkNoWULTj870VXXJupVRviGYDlYO5EJzU69eF8EhcX%2BwFeXllg%2B303pRYZpUDDLlmIy7IdNhLweAuRLNjrQPQ%2BE1wYDrbmn8HgEY0pgINCxcnf%2BLx3EDAoF%2FIr3AyYxBGa8De890N7IcxRXHIEHoqWaq39yJGdG0Dwy2DRuO7IbaW%2BMiGhmfMBZk59%2FzrRB%2Bh%2FR4y7OXmmWiE3eB&X-Amz-Signature=a731216088941b18daf676f54eb6fe3a8567950d9174ecf0f779833144325f8c&X-Amz-SignedHeaders=host&x-amz-checksum-mode=ENABLED&x-id=GetObject)
	配置launch.json后直接使用
	![](https://prod-files-secure.s3.us-west-2.amazonaws.com/f117ffa6-9d35-4dfc-8a5a-12561e26967c/5a0ad5b0-abcc-4e6d-ac12-d22450020a1b/image.png?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Content-Sha256=UNSIGNED-PAYLOAD&X-Amz-Credential=ASIAZI2LB466WOOXGWJ5%2F20260422%2Fus-west-2%2Fs3%2Faws4_request&X-Amz-Date=20260422T074013Z&X-Amz-Expires=3600&X-Amz-Security-Token=IQoJb3JpZ2luX2VjEH4aCXVzLXdlc3QtMiJHMEUCIQDGDHb0NegQO9eNtMTwBdrSIPFiTXQAU%2FbOupstu2Wh6gIgdbz0WEwsrM8wLNCpBBPFG06AyOkxDtb3CcjaOHH7Q98q%2FwMIRxAAGgw2Mzc0MjMxODM4MDUiDIOBD4M7v6mPjOBtbSrcA432GaIxsAXU1O6vA4V4hk7yh09%2FYYPuLIQO3WiCix5TbmTykWveRvfMmG1G9ZLcciXLWadEJ3dCcdg9X%2F28MlOGNSFNv%2Ftqa5k%2FVutRwlXBS%2Fdkpd7tGjzr1M%2F82VaLqakfzcOdt38dyt1Njf9c7cP%2BoGO7qZpPR1Q6MvjYd7tfTMzL870z%2FckBzfkkxo%2BV7QYasbBJzRkGnbI2VY1J9Y%2F4hA5gn1MeAmFLc4v4e3xxUkBvBwvK6c7Fycu5hRUD0lSZJ7Xl38hy9iljXuTGyK%2FgAo2XhsbcYu%2BbLqX%2B%2BZruzRTdMnizPAmxw%2BkSfEtwjgVo4ep71vv9RtXe6p0q%2FjhN3vnYqTR07kMdp%2B492keWICOLrBJF%2FBkVqHpOvkkGy1kS4PRFu%2BVwnS5eIDzOdD1CON31tji5xqB5VaxUrFhdJEmJWk74CpB51fluuAJar1ykOFp7%2BPmEiIInHUYaL7Dw093dhB%2Bruy9uZWss1jPR5Qgq0ItmCYRPA05kRNz4A%2Fa4jrsOohO28lpMFEPluDrwqpCUNI9cwbDIFJFURg3LqLYMcLe81UcldTE3FUzdKndnuVLrXv7%2FtScXdo4SXSgOnySZv9Vb%2BTb6prpvYkE0mDhnXQZT4xmPXbZKMMW9oc8GOqUBOQUOqch9gapzQkNoWULTj870VXXJupVRviGYDlYO5EJzU69eF8EhcX%2BwFeXllg%2B303pRYZpUDDLlmIy7IdNhLweAuRLNjrQPQ%2BE1wYDrbmn8HgEY0pgINCxcnf%2BLx3EDAoF%2FIr3AyYxBGa8De890N7IcxRXHIEHoqWaq39yJGdG0Dwy2DRuO7IbaW%2BMiGhmfMBZk59%2FzrRB%2Bh%2FR4y7OXmmWiE3eB&X-Amz-Signature=27787f22d2b078dffb284fbc04b843e770a61ba98e69f0715c3071a7aee6169b&X-Amz-SignedHeaders=host&x-amz-checksum-mode=ENABLED&x-id=GetObject)
</details>
<details>
</details>
<empty-block/>