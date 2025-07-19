import { Context, Schema, h } from 'koishi';
import fs from 'fs/promises';
import axios from 'axios';
import path from 'path';

export const name = 'ygo-card-search';
export const usage = `点击插件主页前往代码仓库查看详细文档`;

interface Config {
  debug: boolean;
  enableReplace: boolean;
  replaceConfigPath: string;
  maxBatchResults: number;

  // 名称显示配置项
  showCommonName: boolean;
  showMdName: boolean;
  showJpName: boolean;
  showEnName: boolean;
}

export const Config: Schema<Config> = Schema.object({
  debug: Schema.boolean().default(false).description('调试模式，开启时将在控制台打印详细的运行日志'),
  enableReplace: Schema.boolean().default(false).description('是否启用卡片名称替换功能'),
  replaceConfigPath: Schema.path().description('指定包含卡片名称替换规则的 JSON 文件的路径（需包含文件名）'),
  maxBatchResults: Schema.number().default(5).min(1).max(20)
    .description('批量查询时返回的最大结果数量'),

  // 名称显示配置项
  showCommonName: Schema.boolean().default(true).description('是否显示常用名'),
  showMdName: Schema.boolean().default(true).description('是否显示MD卡名'),
  showJpName: Schema.boolean().default(false).description('是否显示日文名'),
  showEnName: Schema.boolean().default(false).description('是否显示英文名'),
});

interface Card {
  id: number;
  cn_name: string;
  md_name: string;
  jp_name: string;
  en_name: string;
  text: {
    types: string;
    desc: string;
    pdesc?: string;
  };
}

export function apply(ctx: Context, config: Config) {
  let replaceConfig: Record<string, string[]> = {};
  const logger = ctx.logger('ygo-card-search');

  // 增强的调试日志函数
  const debugLog = (message: string, data?: any) => {
    if (config.debug) {
      logger.info(`[DEBUG] ${message}`);
      if (data) {
        // 格式化输出对象，限制最大深度
        logger.info(JSON.stringify(data, (key, value) => {
          if (typeof value === 'object' && value !== null) {
            // 限制对象深度为3层
            if (key === 'text' && value.desc && value.desc.length > 100) {
              return `${value.desc.substring(0, 100)}...`;
            }
            return value;
          }
          return value;
        }, 2));
      }
    }
  };

  const loadReplaceConfig = async () => {
    if (!config.enableReplace) return;

    const filePath = path.resolve(config.replaceConfigPath);
    try {
      debugLog(`正在加载替换规则文件: ${filePath}`);
      const rawData = await fs.readFile(filePath, 'utf-8');
      replaceConfig = JSON.parse(rawData);
      debugLog('替换规则成功加载', replaceConfig);
    } catch (error) {
      if (error.code === 'ENOENT') {
        logger.warn('替换规则文件不存在，将创建新文件');
        replaceConfig = {};
        await saveReplaceConfig();
      } else {
        logger.error(`加载替换规则时发生错误: ${error}`);
      }
    }
  };

  const saveReplaceConfig = async () => {
    const filePath = path.resolve(config.replaceConfigPath);
    try {
      debugLog(`正在保存替换规则到: ${filePath}`);
      // 确保目录存在
      await fs.mkdir(path.dirname(filePath), { recursive: true });
      await fs.writeFile(filePath, JSON.stringify(replaceConfig, null, 2), 'utf-8');
      debugLog('替换规则已保存', replaceConfig);
    } catch (error) {
      logger.error(`保存替换规则时发生错误: ${error}`);
    }
  };

  const replaceCardName = (cardname: string): string => {
    debugLog(`应用名称替换规则: ${cardname}`);
    for (const [standardName, aliases] of Object.entries(replaceConfig)) {
      if (aliases.includes(cardname)) {
        debugLog(`找到替换规则: ${cardname} -> ${standardName}`);
        return standardName;
      }
    }
    debugLog(`未找到替换规则: ${cardname}`);
    return cardname;
  };

  const formatCardInfo = (card: Card) => {
    const { id, cn_name, md_name, jp_name, en_name, text } = card;
    const imgUrl = `https://cdn.233.momobako.com/ygopro/pics/${id}.jpg`;

    debugLog(`格式化卡片信息: ${cn_name} (ID: ${id})`, card);

    // 构建名称信息部分，根据配置决定显示哪些字段
    const nameInfo = [];

    // 使用配置项决定是否显示各个名称
    if (config.showCommonName) nameInfo.push(`常用名: ${cn_name}`);
    if (config.showMdName) nameInfo.push(`MD卡名: ${md_name}`);
    if (config.showJpName) nameInfo.push(`日文名: ${jp_name}`);
    if (config.showEnName) nameInfo.push(`英文名: ${en_name}`);

    // 构建卡片描述文本
    let cardText = nameInfo.join('\n');
    cardText += `\n${text.types}\n${text.desc}`;
    if (text.pdesc) cardText += `\n灵摆效果：[${text.pdesc}]`;

    return [
      h.image(imgUrl),
      cardText
    ];
  };

  const filterCardsByType = (cards: Card[], typeFilter: string) => {
    if (!typeFilter) {
      debugLog(`无类型过滤，返回全部 ${cards.length} 张卡片`);
      return cards;
    }

    debugLog(`应用类型过滤: "${typeFilter}"`);

    const filteredCards = cards.filter(card => {
      const typeString = card.text.types.toLowerCase();
      const filters = typeFilter.toLowerCase().split(' ');

      debugLog(`检查卡片: ${card.cn_name}`, {
        types: typeString,
        filters
      });

      return filters.every(filter => {
        if (filter.startsWith('atk:')) {
          const atkValue = parseInt(filter.split(':')[1]);
          const result = typeString.includes(`atk${atkValue}`);
          debugLog(`检查 ATK:${atkValue} -> ${result}`);
          return result;
        }
        if (filter.startsWith('def:')) {
          const defValue = parseInt(filter.split(':')[1]);
          const result = typeString.includes(`def${defValue}`);
          debugLog(`检查 DEF:${defValue} -> ${result}`);
          return result;
        }
        if (filter.startsWith('p:')) {
          const pValue = parseInt(filter.split(':')[1]);
          const result = typeString.includes(`/${pValue}/`);
          debugLog(`检查 P:${pValue} -> ${result}`);
          return result;
        }
        const result = typeString.includes(filter);
        debugLog(`检查 "${filter}" -> ${result}`);
        return result;
      });
    });

    debugLog(`类型过滤后剩余 ${filteredCards.length} 张卡片`);
    return filteredCards;
  };

  const handleApiRequest = async (url: string): Promise<Card[]> => {
    try {
      debugLog(`发起 API 请求: ${url}`);
      const response = await axios.get(url, { timeout: 10000 });
      debugLog(`API 响应成功，返回 ${response.data.result?.length || 0} 张卡片`);
      return response.data.result || [];
    } catch (error) {
      logger.error(`API 请求失败: ${error.message}`);
      debugLog('API 错误详情', error.response?.data || error.message);
      throw new Error('查询卡片信息时发生错误，请稍后再试');
    }
  };

  const handleCardQuery = async ({ session, options }: any, cardname: string) => {
    const typeFilter = options['类型限定'] || '';
    debugLog(`收到卡片查询请求`, {
      cardname,
      typeFilter,
      enableReplace: config.enableReplace
    });

    if (!cardname) return '错误: 请输入卡片名称';

    // 应用替换规则
    const originalName = cardname;
    if (config.enableReplace) {
      cardname = replaceCardName(cardname);
      if (originalName !== cardname) {
        debugLog(`名称替换: "${originalName}" → "${cardname}"`);
      } else {
        debugLog(`无替换规则: "${cardname}"`);
      }
    }

    try {
      const cardList = await handleApiRequest(`https://ygocdb.com/api/v0/?search=${encodeURIComponent(cardname)}`);
      if (!cardList.length) {
        debugLog(`未找到卡片: ${cardname}`);
        return `未找到卡片: ${cardname}`;
      }

      debugLog(`找到 ${cardList.length} 张卡片`, cardList.map(c => c.cn_name));

      const filteredCards = filterCardsByType(cardList, typeFilter);
      if (!filteredCards.length) {
        debugLog(`无符合类型条件的卡片`, {
          typeFilter,
          totalCards: cardList.length
        });
        return `没有找到符合类型条件的卡片: ${typeFilter || '无'}`;
      }

      return formatCardInfo(filteredCards[0]);
    } catch (error) {
      debugLog(`查询过程中发生错误`, error);
      return error.message;
    }
  };

  const handleBatchQuery = async ({ session, options }: any, cardname: string) => {
    debugLog(`收到批量查询请求`, {
      cardname,
      maxResults: options.最大数量 || 5
    });

    if (!cardname) return '错误: 请输入卡片名称';

    try {
      const cardList = await handleApiRequest(`https://ygocdb.com/api/v0/?search=${encodeURIComponent(cardname)}`);
      if (!cardList.length) {
        debugLog(`未找到卡片: ${cardname}`);
        return `未找到卡片: ${cardname}`;
      }

      debugLog(`找到 ${cardList.length} 张卡片`, cardList.map(c => c.cn_name));

      // 限制返回结果数量
      const maxResults = Math.min(options.最大数量 || 5, config.maxBatchResults);
      const results = cardList.slice(0, maxResults);
      debugLog(`返回前 ${results.length} 张卡片`, results.map(c => c.cn_name));

      // 使用消息段构建转发消息
      const messages = results.flatMap(card => formatCardInfo(card));
      return h('forward', messages.map(msg => h('message', msg)));
    } catch (error) {
      debugLog(`批量查询过程中发生错误`, error);
      return error.message;
    }
  };

  const manageReplaceConfig = async (args: string | undefined, action: 'add' | 'delete') => {
    const [standardName, alias] = args?.split(':').map(s => s.trim()) || [];
    if (!standardName || !alias) return `格式错误，正确格式为：rpcfg ${action} 标准卡名:别名`;

    debugLog(`执行替换规则操作: ${action}`, {
      standardName,
      alias,
      currentConfig: replaceConfig
    });

    if (action === 'add') {
      // 检查别名是否已被使用
      for (const [key, aliases] of Object.entries(replaceConfig)) {
        if (aliases.includes(alias)) {
          debugLog(`别名已被使用: ${alias} -> ${key}`);
          return `别名 "${alias}" 已被标准卡名 "${key}" 使用`;
        }
      }

      if (!replaceConfig[standardName]) {
        replaceConfig[standardName] = [];
        debugLog(`创建新标准名: ${standardName}`);
      }

      if (!replaceConfig[standardName].includes(alias)) {
        replaceConfig[standardName].push(alias);
        await saveReplaceConfig();
        debugLog(`添加新别名: ${alias} -> ${standardName}`);
        return `添加成功: ${alias} → ${standardName}`;
      }
      debugLog(`别名已存在: ${alias} -> ${standardName}`);
      return `别名已存在: ${alias}`;
    }

    if (action === 'delete') {
      if (!replaceConfig[standardName] || !replaceConfig[standardName].includes(alias)) {
        debugLog(`别名不存在: ${alias} -> ${standardName}`);
        return `别名不存在: ${alias}`;
      }

      replaceConfig[standardName] = replaceConfig[standardName].filter(a => a !== alias);
      debugLog(`删除别名: ${alias} -> ${standardName}`);

      // 清理空条目
      if (replaceConfig[standardName].length === 0) {
        delete replaceConfig[standardName];
        debugLog(`清理空标准名: ${standardName}`);
      }

      await saveReplaceConfig();
      return `删除成功: ${alias} → ${standardName}`;
    }

    return '未知操作';
  };

  ctx.command('ck <cardname:text>', '查询游戏王卡片信息')
    .alias('查卡')
    .option('类型限定', '-d [type]', { fallback: '' })
    .action(handleCardQuery);

  ctx.command('pl <cardname:text>', '批量查询卡片信息')
    .alias('批量查卡')
    .option('最大数量', '-n [number]', { fallback: 5 })
    .action(handleBatchQuery);

  ctx.command('rpcfg <action:string> [args:text]', '管理替换规则')
    .action(async ({ session }, action, args) => {
      if (!config.enableReplace) return '替换功能未启用，请在配置中开启';

      debugLog(`收到替换规则操作: ${action}`, { args });

      switch (action) {
        case 'reload':
          await loadReplaceConfig();
          return '替换规则已重新加载';
        case 'add':
        case 'delete':
          return await manageReplaceConfig(args, action);
        default:
          return '未知操作，支持的操作: add, delete, reload';
      }
    });

  // 初始加载替换规则
  loadReplaceConfig().catch(err => {
    logger.error(`初始化加载替换规则失败: ${err}`);
  });
}
