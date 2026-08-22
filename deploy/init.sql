-- PostgreSQL 初始化脚本：可重复执行，不会重复创建默认账号和示例用例。
CREATE TABLE IF NOT EXISTS "user" (
  id BIGSERIAL PRIMARY KEY,
  username VARCHAR(64) NOT NULL UNIQUE,
  password VARCHAR(100) NOT NULL,
  nickname VARCHAR(64) NOT NULL,
  create_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS test_case (
  id BIGSERIAL PRIMARY KEY,
  title VARCHAR(255) NOT NULL,
  module VARCHAR(100) NOT NULL,
  priority VARCHAR(10) NOT NULL,
  status VARCHAR(20) NOT NULL,
  description TEXT,
  expected_result TEXT,
  creator VARCHAR(64) NOT NULL,
  create_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  update_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
-- BCrypt("123456")，仅作为练手默认账号。
INSERT INTO "user" (username, password, nickname)
VALUES ('admin', '$2a$10$09BFwxsJX3my0XsPDpIi/uC.n8Tyr2Wb/oylH0gSGOaMSVjRw.yaK', '管理员')
ON CONFLICT (username) DO NOTHING;
INSERT INTO test_case (title,module,priority,status,description,expected_result,creator)
SELECT v.title,v.module,v.priority,v.status,v.description,v.expected_result,v.creator
FROM (VALUES
  ('管理员正确登录','用户认证','P0','通过','使用 admin / 123456 登录。','登录成功并进入管理页。','管理员'),
  ('错误密码登录提示','用户认证','P1','通过','输入错误密码。','提示用户名或密码错误。','管理员'),
  ('新建用例必填校验','用例管理','P1','未执行','不填写标题提交。','提示标题必填。','管理员'),
  ('筛选优先级 P0','用例管理','P2','失败','筛选 P0。','仅显示 P0 用例。','管理员'),
  ('删除用例二次确认','用例管理','P3','阻塞','点击删除。','确认后才删除。','管理员')
) AS v(title,module,priority,status,description,expected_result,creator)
WHERE NOT EXISTS (SELECT 1 FROM test_case);
