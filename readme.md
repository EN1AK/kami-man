# koishi-plugin-ygo-card-search

[![npm](https://img.shields.io/npm/v/koishi-plugin-ygo-card-search?style=flat-square)](https://www.npmjs.com/package/koishi-plugin-ygo-card-search)

开发中的适用于Koishi的游戏王查卡插件，使用 百鸽（ygocdb.com） 的API获取数据。

## 如何使用
命令`ck`或`查卡`后空格+卡名即可查询卡片信息。目前在不打开卡片名称替换的情况下，只能严格匹配原本卡名。
使用例：`ck 灰流丽`，`查卡 灰流丽`

## 卡片名称替换
替换规则的 JSON 文件格式如下：
```json
{
"暗黑大法师": "艾克佐迪亚",
"黑暗大法师": "艾克佐迪亚",
"刻魔": "刻印群魔的刻魔锻冶师"
}
```
前面的键是要被替换的卡片名称，后面的值是替换后的卡片名称。
例如这里，暗黑大法师和黑暗大法师会被替换为艾克佐迪亚，
刻魔会被替换为刻印群魔的刻魔锻冶师。
**注意！** 请不要尝试设置两个相同的键，这是**未经测试**的行为，可能会导致**不预期的结果！**