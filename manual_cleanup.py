#!/usr/bin/env python3
"""
手动清理脚本 - 用于清理两个账户的挂单和持仓
"""

import asyncio
import time
from binance_connector import BinanceConnector
from config import get_account_config, ALL_CONFIG
from utils.logger import setup_logging, get_main_logger


async def manual_cleanup():
    """手动清理两个账户"""
    
    # 设置日志
    setup_logging()
    logger = get_main_logger()
    
    logger.info("=" * 80)
    logger.info("  手动清理脚本启动")
    logger.info("=" * 80)
    
    try:
        # 获取配置
        trading_config = ALL_CONFIG["trading"]
        account_a_config = get_account_config("A")
        account_b_config = get_account_config("B")
        
        # 创建连接器
        logger.info("创建连接器...")
        
        connector_a = BinanceConnector(
            api_key=account_a_config["api_key"],
            api_secret=account_a_config["api_secret"],
            trading_pair=trading_config["pair"],
            contract_type=trading_config["contract_type"],
            leverage=trading_config["leverage"],
            account_name="Account_A_Manual_Cleanup"
        )
        
        connector_b = BinanceConnector(
            api_key=account_b_config["api_key"],
            api_secret=account_b_config["api_secret"],
            trading_pair=trading_config["pair"],
            contract_type=trading_config["contract_type"],
            leverage=trading_config["leverage"],
            account_name="Account_B_Manual_Cleanup"
        )
        
        # 检查当前状态
        logger.info("\n" + "=" * 50)
        logger.info("  清理前状态检查")
        logger.info("=" * 50)
        
        # 账户A状态
        logger.info("账户A状态:")
        orders_a = connector_a.get_open_orders()
        long_pos_a, short_pos_a = connector_a.get_positions()
        logger.info(f"  挂单数量: {len(orders_a)}")
        logger.info(f"  多头持仓: {long_pos_a}")
        logger.info(f"  空头持仓: {short_pos_a}")
        
        # 账户B状态
        logger.info("账户B状态:")
        orders_b = connector_b.get_open_orders()
        long_pos_b, short_pos_b = connector_b.get_positions()
        logger.info(f"  挂单数量: {len(orders_b)}")
        logger.info(f"  多头持仓: {long_pos_b}")
        logger.info(f"  空头持仓: {short_pos_b}")
        
        # 开始清理
        logger.info("\n" + "=" * 50)
        logger.info("  开始清理")
        logger.info("=" * 50)
        
        # 并行清理两个账户
        loop = asyncio.get_event_loop()
        cleanup_tasks = [
            loop.run_in_executor(None, connector_a.cleanup),
            loop.run_in_executor(None, connector_b.cleanup)
        ]
        
        logger.info("执行并行清理...")
        results = await asyncio.gather(*cleanup_tasks, return_exceptions=True)
        
        # 检查清理结果
        success_a = results[0] if not isinstance(results[0], Exception) else False
        success_b = results[1] if not isinstance(results[1], Exception) else False
        
        if isinstance(results[0], Exception):
            logger.error(f"账户A清理失败: {results[0]}")
        else:
            logger.info(f"账户A清理结果: {'成功' if success_a else '失败'}")
            
        if isinstance(results[1], Exception):
            logger.error(f"账户B清理失败: {results[1]}")
        else:
            logger.info(f"账户B清理结果: {'成功' if success_b else '失败'}")
        
        # 等待一下
        logger.info("等待3秒后验证清理结果...")
        await asyncio.sleep(3)
        
        # 验证清理结果
        logger.info("\n" + "=" * 50)
        logger.info("  清理后状态验证")
        logger.info("=" * 50)
        
        # 账户A验证
        logger.info("账户A验证:")
        orders_a_after = connector_a.get_open_orders()
        long_pos_a_after, short_pos_a_after = connector_a.get_positions()
        logger.info(f"  挂单数量: {len(orders_a_after)} (清理前: {len(orders_a)})")
        logger.info(f"  多头持仓: {long_pos_a_after} (清理前: {long_pos_a})")
        logger.info(f"  空头持仓: {short_pos_a_after} (清理前: {short_pos_a})")
        
        # 账户B验证
        logger.info("账户B验证:")
        orders_b_after = connector_b.get_open_orders()
        long_pos_b_after, short_pos_b_after = connector_b.get_positions()
        logger.info(f"  挂单数量: {len(orders_b_after)} (清理前: {len(orders_b)})")
        logger.info(f"  多头持仓: {long_pos_b_after} (清理前: {long_pos_b})")
        logger.info(f"  空头持仓: {short_pos_b_after} (清理前: {short_pos_b})")
        
        # 总结
        logger.info("\n" + "=" * 50)
        logger.info("  清理总结")
        logger.info("=" * 50)
        
        total_orders_before = len(orders_a) + len(orders_b)
        total_orders_after = len(orders_a_after) + len(orders_b_after)
        
        total_positions_before = abs(long_pos_a) + abs(short_pos_a) + abs(long_pos_b) + abs(short_pos_b)
        total_positions_after = abs(long_pos_a_after) + abs(short_pos_a_after) + abs(long_pos_b_after) + abs(short_pos_b_after)
        
        logger.info(f"挂单清理: {total_orders_before} -> {total_orders_after}")
        logger.info(f"持仓清理: {total_positions_before:.6f} -> {total_positions_after:.6f}")
        
        if total_orders_after == 0 and total_positions_after == 0:
            logger.info("✅ 清理完全成功！")
        else:
            logger.warning("⚠️ 清理不完全，可能需要手动处理剩余订单/持仓")
            
            if total_orders_after > 0:
                logger.warning(f"剩余挂单: {total_orders_after}")
            if total_positions_after > 0:
                logger.warning(f"剩余持仓: {total_positions_after:.6f}")
        
        return total_orders_after == 0 and total_positions_after == 0
        
    except Exception as e:
        logger.error(f"手动清理失败: {e}", exc_info=True)
        return False


def main():
    """主函数"""
    try:
        result = asyncio.run(manual_cleanup())
        if result:
            print("\n🎉 手动清理成功完成！")
        else:
            print("\n❌ 手动清理未完全成功，请检查日志。")
    except KeyboardInterrupt:
        print("\n用户中断清理过程")
    except Exception as e:
        print(f"\n清理过程出错: {e}")


if __name__ == "__main__":
    main()
