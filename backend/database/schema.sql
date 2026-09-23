-- =====================================================================
-- ProcureFlow / Procurement — Skema MariaDB (dibuat oleh scripts/generate_schema.py)
-- ---------------------------------------------------------------------
-- Satu tabel per koleksi. Kolom `doc` = dokumen JSON lengkap; kolom lain
-- adalah kolom GENERATED (turunan dari doc) agar mudah dibaca di phpMyAdmin
-- dan bisa diindeks. Jangan mengubah kolom generated secara manual.
-- File ini idempoten (aman dijalankan berulang).
-- =====================================================================

-- ---- adjustment_lines (0 dokumen contoh) ----
CREATE TABLE IF NOT EXISTS `adjustment_lines` (
  pk VARCHAR(64) NOT NULL PRIMARY KEY COMMENT 'doc.id atau UUID',
  doc LONGTEXT NOT NULL COMMENT 'Dokumen lengkap (JSON)' CHECK (JSON_VALID(doc)),
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  KEY idx_adjustment_lines_created (created_at, pk)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Koleksi adjustment_lines (ProcureFlow)';
ALTER TABLE `adjustment_lines` ADD COLUMN IF NOT EXISTS `id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.id'), 191)) STORED;
ALTER TABLE `adjustment_lines` ADD INDEX IF NOT EXISTS `idx_adjustment_lines_id` (`id`);
ALTER TABLE `adjustment_lines` ADD COLUMN IF NOT EXISTS `code` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.code'), 191)) STORED;
ALTER TABLE `adjustment_lines` ADD INDEX IF NOT EXISTS `idx_adjustment_lines_code` (`code`);
ALTER TABLE `adjustment_lines` ADD COLUMN IF NOT EXISTS `no` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.no'), 191)) STORED;
ALTER TABLE `adjustment_lines` ADD INDEX IF NOT EXISTS `idx_adjustment_lines_no` (`no`);
ALTER TABLE `adjustment_lines` ADD COLUMN IF NOT EXISTS `status` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.status'), 191)) STORED;
ALTER TABLE `adjustment_lines` ADD INDEX IF NOT EXISTS `idx_adjustment_lines_status` (`status`);

-- ---- adjustments (0 dokumen contoh) ----
CREATE TABLE IF NOT EXISTS `adjustments` (
  pk VARCHAR(64) NOT NULL PRIMARY KEY COMMENT 'doc.id atau UUID',
  doc LONGTEXT NOT NULL COMMENT 'Dokumen lengkap (JSON)' CHECK (JSON_VALID(doc)),
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  KEY idx_adjustments_created (created_at, pk)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Koleksi adjustments (ProcureFlow)';
ALTER TABLE `adjustments` ADD COLUMN IF NOT EXISTS `id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.id'), 191)) STORED;
ALTER TABLE `adjustments` ADD INDEX IF NOT EXISTS `idx_adjustments_id` (`id`);
ALTER TABLE `adjustments` ADD COLUMN IF NOT EXISTS `code` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.code'), 191)) STORED;
ALTER TABLE `adjustments` ADD INDEX IF NOT EXISTS `idx_adjustments_code` (`code`);
ALTER TABLE `adjustments` ADD COLUMN IF NOT EXISTS `no` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.no'), 191)) STORED;
ALTER TABLE `adjustments` ADD INDEX IF NOT EXISTS `idx_adjustments_no` (`no`);
ALTER TABLE `adjustments` ADD COLUMN IF NOT EXISTS `status` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.status'), 191)) STORED;
ALTER TABLE `adjustments` ADD INDEX IF NOT EXISTS `idx_adjustments_status` (`status`);

-- ---- allocations (6 dokumen contoh) ----
CREATE TABLE IF NOT EXISTS `allocations` (
  pk VARCHAR(64) NOT NULL PRIMARY KEY COMMENT 'doc.id atau UUID',
  doc LONGTEXT NOT NULL COMMENT 'Dokumen lengkap (JSON)' CHECK (JSON_VALID(doc)),
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  KEY idx_allocations_created (created_at, pk)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Koleksi allocations (ProcureFlow)';
ALTER TABLE `allocations` ADD COLUMN IF NOT EXISTS `id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.id'), 191)) STORED;
ALTER TABLE `allocations` ADD INDEX IF NOT EXISTS `idx_allocations_id` (`id`);
ALTER TABLE `allocations` ADD COLUMN IF NOT EXISTS `at` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.at'), 191)) STORED;
ALTER TABLE `allocations` ADD INDEX IF NOT EXISTS `idx_allocations_at` (`at`);
ALTER TABLE `allocations` ADD COLUMN IF NOT EXISTS `item_id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.item_id'), 191)) STORED;
ALTER TABLE `allocations` ADD INDEX IF NOT EXISTS `idx_allocations_item_id` (`item_id`);
ALTER TABLE `allocations` ADD COLUMN IF NOT EXISTS `source_doc_id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.source_doc_id'), 191)) STORED;
ALTER TABLE `allocations` ADD INDEX IF NOT EXISTS `idx_allocations_source_doc_id` (`source_doc_id`);
ALTER TABLE `allocations` ADD COLUMN IF NOT EXISTS `source_line_id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.source_line_id'), 191)) STORED;
ALTER TABLE `allocations` ADD INDEX IF NOT EXISTS `idx_allocations_source_line_id` (`source_line_id`);
ALTER TABLE `allocations` ADD COLUMN IF NOT EXISTS `source_type` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.source_type'), 191)) STORED;
ALTER TABLE `allocations` ADD INDEX IF NOT EXISTS `idx_allocations_source_type` (`source_type`);
ALTER TABLE `allocations` ADD COLUMN IF NOT EXISTS `target_doc_id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.target_doc_id'), 191)) STORED;
ALTER TABLE `allocations` ADD INDEX IF NOT EXISTS `idx_allocations_target_doc_id` (`target_doc_id`);
ALTER TABLE `allocations` ADD COLUMN IF NOT EXISTS `target_line_id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.target_line_id'), 191)) STORED;
ALTER TABLE `allocations` ADD INDEX IF NOT EXISTS `idx_allocations_target_line_id` (`target_line_id`);
ALTER TABLE `allocations` ADD COLUMN IF NOT EXISTS `target_type` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.target_type'), 191)) STORED;
ALTER TABLE `allocations` ADD INDEX IF NOT EXISTS `idx_allocations_target_type` (`target_type`);
ALTER TABLE `allocations` ADD COLUMN IF NOT EXISTS `qty` TEXT AS (JSON_VALUE(doc, '$.qty')) STORED;

-- ---- approval_tasks (3 dokumen contoh) ----
CREATE TABLE IF NOT EXISTS `approval_tasks` (
  pk VARCHAR(64) NOT NULL PRIMARY KEY COMMENT 'doc.id atau UUID',
  doc LONGTEXT NOT NULL COMMENT 'Dokumen lengkap (JSON)' CHECK (JSON_VALID(doc)),
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  KEY idx_approval_tasks_created (created_at, pk)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Koleksi approval_tasks (ProcureFlow)';
ALTER TABLE `approval_tasks` ADD COLUMN IF NOT EXISTS `id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.id'), 191)) STORED;
ALTER TABLE `approval_tasks` ADD INDEX IF NOT EXISTS `idx_approval_tasks_id` (`id`);
ALTER TABLE `approval_tasks` ADD COLUMN IF NOT EXISTS `acted_at` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.acted_at'), 191)) STORED;
ALTER TABLE `approval_tasks` ADD INDEX IF NOT EXISTS `idx_approval_tasks_acted_at` (`acted_at`);
ALTER TABLE `approval_tasks` ADD COLUMN IF NOT EXISTS `acted_by` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.acted_by'), 191)) STORED;
ALTER TABLE `approval_tasks` ADD INDEX IF NOT EXISTS `idx_approval_tasks_acted_by` (`acted_by`);
ALTER TABLE `approval_tasks` ADD COLUMN IF NOT EXISTS `approver_user_id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.approver_user_id'), 191)) STORED;
ALTER TABLE `approval_tasks` ADD INDEX IF NOT EXISTS `idx_approval_tasks_approver_user_id` (`approver_user_id`);
ALTER TABLE `approval_tasks` ADD COLUMN IF NOT EXISTS `document_id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.document_id'), 191)) STORED;
ALTER TABLE `approval_tasks` ADD INDEX IF NOT EXISTS `idx_approval_tasks_document_id` (`document_id`);
ALTER TABLE `approval_tasks` ADD COLUMN IF NOT EXISTS `document_no` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.document_no'), 191)) STORED;
ALTER TABLE `approval_tasks` ADD INDEX IF NOT EXISTS `idx_approval_tasks_document_no` (`document_no`);
ALTER TABLE `approval_tasks` ADD COLUMN IF NOT EXISTS `document_type` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.document_type'), 191)) STORED;
ALTER TABLE `approval_tasks` ADD INDEX IF NOT EXISTS `idx_approval_tasks_document_type` (`document_type`);
ALTER TABLE `approval_tasks` ADD COLUMN IF NOT EXISTS `module` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.module'), 191)) STORED;
ALTER TABLE `approval_tasks` ADD INDEX IF NOT EXISTS `idx_approval_tasks_module` (`module`);
ALTER TABLE `approval_tasks` ADD COLUMN IF NOT EXISTS `status` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.status'), 191)) STORED;
ALTER TABLE `approval_tasks` ADD INDEX IF NOT EXISTS `idx_approval_tasks_status` (`status`);
ALTER TABLE `approval_tasks` ADD COLUMN IF NOT EXISTS `seq` TEXT AS (JSON_VALUE(doc, '$.seq')) STORED;
ALTER TABLE `approval_tasks` ADD COLUMN IF NOT EXISTS `level` TEXT AS (JSON_VALUE(doc, '$.level')) STORED;
ALTER TABLE `approval_tasks` ADD COLUMN IF NOT EXISTS `approver_email` TEXT AS (JSON_VALUE(doc, '$.approver_email')) STORED;
ALTER TABLE `approval_tasks` ADD COLUMN IF NOT EXISTS `approver_name` TEXT AS (JSON_VALUE(doc, '$.approver_name')) STORED;
ALTER TABLE `approval_tasks` ADD COLUMN IF NOT EXISTS `acted_by_email` TEXT AS (JSON_VALUE(doc, '$.acted_by_email')) STORED;
ALTER TABLE `approval_tasks` ADD COLUMN IF NOT EXISTS `note` TEXT AS (JSON_VALUE(doc, '$.note')) STORED;

-- ---- attachments (2 dokumen contoh) ----
CREATE TABLE IF NOT EXISTS `attachments` (
  pk VARCHAR(64) NOT NULL PRIMARY KEY COMMENT 'doc.id atau UUID',
  doc LONGTEXT NOT NULL COMMENT 'Dokumen lengkap (JSON)' CHECK (JSON_VALID(doc)),
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  KEY idx_attachments_created (created_at, pk)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Koleksi attachments (ProcureFlow)';
ALTER TABLE `attachments` ADD COLUMN IF NOT EXISTS `id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.id'), 191)) STORED;
ALTER TABLE `attachments` ADD INDEX IF NOT EXISTS `idx_attachments_id` (`id`);
ALTER TABLE `attachments` ADD COLUMN IF NOT EXISTS `category` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.category'), 191)) STORED;
ALTER TABLE `attachments` ADD INDEX IF NOT EXISTS `idx_attachments_category` (`category`);
ALTER TABLE `attachments` ADD COLUMN IF NOT EXISTS `content_type` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.content_type'), 191)) STORED;
ALTER TABLE `attachments` ADD INDEX IF NOT EXISTS `idx_attachments_content_type` (`content_type`);
ALTER TABLE `attachments` ADD COLUMN IF NOT EXISTS `entity` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.entity'), 191)) STORED;
ALTER TABLE `attachments` ADD INDEX IF NOT EXISTS `idx_attachments_entity` (`entity`);
ALTER TABLE `attachments` ADD COLUMN IF NOT EXISTS `entity_id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.entity_id'), 191)) STORED;
ALTER TABLE `attachments` ADD INDEX IF NOT EXISTS `idx_attachments_entity_id` (`entity_id`);
ALTER TABLE `attachments` ADD COLUMN IF NOT EXISTS `is_deleted` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.is_deleted'), 191)) STORED;
ALTER TABLE `attachments` ADD INDEX IF NOT EXISTS `idx_attachments_is_deleted` (`is_deleted`);
ALTER TABLE `attachments` ADD COLUMN IF NOT EXISTS `uploaded_by` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.uploaded_by'), 191)) STORED;
ALTER TABLE `attachments` ADD INDEX IF NOT EXISTS `idx_attachments_uploaded_by` (`uploaded_by`);
ALTER TABLE `attachments` ADD COLUMN IF NOT EXISTS `storage_path` TEXT AS (JSON_VALUE(doc, '$.storage_path')) STORED;
ALTER TABLE `attachments` ADD COLUMN IF NOT EXISTS `original_filename` TEXT AS (JSON_VALUE(doc, '$.original_filename')) STORED;
ALTER TABLE `attachments` ADD COLUMN IF NOT EXISTS `size` TEXT AS (JSON_VALUE(doc, '$.size')) STORED;
ALTER TABLE `attachments` ADD COLUMN IF NOT EXISTS `note` TEXT AS (JSON_VALUE(doc, '$.note')) STORED;

-- ---- audit_logs (1438 dokumen contoh) ----
CREATE TABLE IF NOT EXISTS `audit_logs` (
  pk VARCHAR(64) NOT NULL PRIMARY KEY COMMENT 'doc.id atau UUID',
  doc LONGTEXT NOT NULL COMMENT 'Dokumen lengkap (JSON)' CHECK (JSON_VALID(doc)),
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  KEY idx_audit_logs_created (created_at, pk)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Koleksi audit_logs (ProcureFlow)';
ALTER TABLE `audit_logs` ADD COLUMN IF NOT EXISTS `id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.id'), 191)) STORED;
ALTER TABLE `audit_logs` ADD INDEX IF NOT EXISTS `idx_audit_logs_id` (`id`);
ALTER TABLE `audit_logs` ADD COLUMN IF NOT EXISTS `action` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.action'), 191)) STORED;
ALTER TABLE `audit_logs` ADD INDEX IF NOT EXISTS `idx_audit_logs_action` (`action`);
ALTER TABLE `audit_logs` ADD COLUMN IF NOT EXISTS `at` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.at'), 191)) STORED;
ALTER TABLE `audit_logs` ADD INDEX IF NOT EXISTS `idx_audit_logs_at` (`at`);
ALTER TABLE `audit_logs` ADD COLUMN IF NOT EXISTS `doc_no` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.doc_no'), 191)) STORED;
ALTER TABLE `audit_logs` ADD INDEX IF NOT EXISTS `idx_audit_logs_doc_no` (`doc_no`);
ALTER TABLE `audit_logs` ADD COLUMN IF NOT EXISTS `entity` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.entity'), 191)) STORED;
ALTER TABLE `audit_logs` ADD INDEX IF NOT EXISTS `idx_audit_logs_entity` (`entity`);
ALTER TABLE `audit_logs` ADD COLUMN IF NOT EXISTS `entity_id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.entity_id'), 191)) STORED;
ALTER TABLE `audit_logs` ADD INDEX IF NOT EXISTS `idx_audit_logs_entity_id` (`entity_id`);
ALTER TABLE `audit_logs` ADD COLUMN IF NOT EXISTS `user` TEXT AS (JSON_VALUE(doc, '$.user')) STORED;
ALTER TABLE `audit_logs` ADD COLUMN IF NOT EXISTS `user_name` TEXT AS (JSON_VALUE(doc, '$.user_name')) STORED;
ALTER TABLE `audit_logs` ADD COLUMN IF NOT EXISTS `reason` TEXT AS (JSON_VALUE(doc, '$.reason')) STORED;

-- ---- contacts (1 dokumen contoh) ----
CREATE TABLE IF NOT EXISTS `contacts` (
  pk VARCHAR(64) NOT NULL PRIMARY KEY COMMENT 'doc.id atau UUID',
  doc LONGTEXT NOT NULL COMMENT 'Dokumen lengkap (JSON)' CHECK (JSON_VALID(doc)),
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  KEY idx_contacts_created (created_at, pk)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Koleksi contacts (ProcureFlow)';
ALTER TABLE `contacts` ADD COLUMN IF NOT EXISTS `id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.id'), 191)) STORED;
ALTER TABLE `contacts` ADD INDEX IF NOT EXISTS `idx_contacts_id` (`id`);
ALTER TABLE `contacts` ADD COLUMN IF NOT EXISTS `code` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.code'), 191)) STORED;
ALTER TABLE `contacts` ADD INDEX IF NOT EXISTS `idx_contacts_code` (`code`);
ALTER TABLE `contacts` ADD COLUMN IF NOT EXISTS `email` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.email'), 191)) STORED;
ALTER TABLE `contacts` ADD INDEX IF NOT EXISTS `idx_contacts_email` (`email`);
ALTER TABLE `contacts` ADD COLUMN IF NOT EXISTS `is_active` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.is_active'), 191)) STORED;
ALTER TABLE `contacts` ADD INDEX IF NOT EXISTS `idx_contacts_is_active` (`is_active`);
ALTER TABLE `contacts` ADD COLUMN IF NOT EXISTS `name` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.name'), 191)) STORED;
ALTER TABLE `contacts` ADD INDEX IF NOT EXISTS `idx_contacts_name` (`name`);
ALTER TABLE `contacts` ADD COLUMN IF NOT EXISTS `position` TEXT AS (JSON_VALUE(doc, '$.position')) STORED;
ALTER TABLE `contacts` ADD COLUMN IF NOT EXISTS `phone` TEXT AS (JSON_VALUE(doc, '$.phone')) STORED;

-- ---- counters (19 dokumen contoh) ----
CREATE TABLE IF NOT EXISTS `counters` (
  pk VARCHAR(64) NOT NULL PRIMARY KEY COMMENT 'doc.id atau UUID',
  doc LONGTEXT NOT NULL COMMENT 'Dokumen lengkap (JSON)' CHECK (JSON_VALID(doc)),
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  KEY idx_counters_created (created_at, pk)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Koleksi counters (ProcureFlow)';
ALTER TABLE `counters` ADD COLUMN IF NOT EXISTS `id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.id'), 191)) STORED;
ALTER TABLE `counters` ADD INDEX IF NOT EXISTS `idx_counters_id` (`id`);
ALTER TABLE `counters` ADD COLUMN IF NOT EXISTS `seq` TEXT AS (JSON_VALUE(doc, '$.seq')) STORED;

-- ---- divisions (5 dokumen contoh) ----
CREATE TABLE IF NOT EXISTS `divisions` (
  pk VARCHAR(64) NOT NULL PRIMARY KEY COMMENT 'doc.id atau UUID',
  doc LONGTEXT NOT NULL COMMENT 'Dokumen lengkap (JSON)' CHECK (JSON_VALID(doc)),
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  KEY idx_divisions_created (created_at, pk)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Koleksi divisions (ProcureFlow)';
ALTER TABLE `divisions` ADD COLUMN IF NOT EXISTS `id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.id'), 191)) STORED;
ALTER TABLE `divisions` ADD INDEX IF NOT EXISTS `idx_divisions_id` (`id`);
ALTER TABLE `divisions` ADD COLUMN IF NOT EXISTS `code` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.code'), 191)) STORED;
ALTER TABLE `divisions` ADD INDEX IF NOT EXISTS `idx_divisions_code` (`code`);
ALTER TABLE `divisions` ADD COLUMN IF NOT EXISTS `is_active` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.is_active'), 191)) STORED;
ALTER TABLE `divisions` ADD INDEX IF NOT EXISTS `idx_divisions_is_active` (`is_active`);
ALTER TABLE `divisions` ADD COLUMN IF NOT EXISTS `name` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.name'), 191)) STORED;
ALTER TABLE `divisions` ADD INDEX IF NOT EXISTS `idx_divisions_name` (`name`);

-- ---- do (0 dokumen contoh) ----
CREATE TABLE IF NOT EXISTS `do` (
  pk VARCHAR(64) NOT NULL PRIMARY KEY COMMENT 'doc.id atau UUID',
  doc LONGTEXT NOT NULL COMMENT 'Dokumen lengkap (JSON)' CHECK (JSON_VALID(doc)),
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  KEY idx_do_created (created_at, pk)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Koleksi do (ProcureFlow)';
ALTER TABLE `do` ADD COLUMN IF NOT EXISTS `id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.id'), 191)) STORED;
ALTER TABLE `do` ADD INDEX IF NOT EXISTS `idx_do_id` (`id`);
ALTER TABLE `do` ADD COLUMN IF NOT EXISTS `code` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.code'), 191)) STORED;
ALTER TABLE `do` ADD INDEX IF NOT EXISTS `idx_do_code` (`code`);
ALTER TABLE `do` ADD COLUMN IF NOT EXISTS `no` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.no'), 191)) STORED;
ALTER TABLE `do` ADD INDEX IF NOT EXISTS `idx_do_no` (`no`);
ALTER TABLE `do` ADD COLUMN IF NOT EXISTS `status` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.status'), 191)) STORED;
ALTER TABLE `do` ADD INDEX IF NOT EXISTS `idx_do_status` (`status`);

-- ---- do_lines (0 dokumen contoh) ----
CREATE TABLE IF NOT EXISTS `do_lines` (
  pk VARCHAR(64) NOT NULL PRIMARY KEY COMMENT 'doc.id atau UUID',
  doc LONGTEXT NOT NULL COMMENT 'Dokumen lengkap (JSON)' CHECK (JSON_VALID(doc)),
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  KEY idx_do_lines_created (created_at, pk)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Koleksi do_lines (ProcureFlow)';
ALTER TABLE `do_lines` ADD COLUMN IF NOT EXISTS `id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.id'), 191)) STORED;
ALTER TABLE `do_lines` ADD INDEX IF NOT EXISTS `idx_do_lines_id` (`id`);
ALTER TABLE `do_lines` ADD COLUMN IF NOT EXISTS `code` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.code'), 191)) STORED;
ALTER TABLE `do_lines` ADD INDEX IF NOT EXISTS `idx_do_lines_code` (`code`);
ALTER TABLE `do_lines` ADD COLUMN IF NOT EXISTS `no` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.no'), 191)) STORED;
ALTER TABLE `do_lines` ADD INDEX IF NOT EXISTS `idx_do_lines_no` (`no`);
ALTER TABLE `do_lines` ADD COLUMN IF NOT EXISTS `status` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.status'), 191)) STORED;
ALTER TABLE `do_lines` ADD INDEX IF NOT EXISTS `idx_do_lines_status` (`status`);

-- ---- item_categories (10 dokumen contoh) ----
CREATE TABLE IF NOT EXISTS `item_categories` (
  pk VARCHAR(64) NOT NULL PRIMARY KEY COMMENT 'doc.id atau UUID',
  doc LONGTEXT NOT NULL COMMENT 'Dokumen lengkap (JSON)' CHECK (JSON_VALID(doc)),
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  KEY idx_item_categories_created (created_at, pk)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Koleksi item_categories (ProcureFlow)';
ALTER TABLE `item_categories` ADD COLUMN IF NOT EXISTS `id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.id'), 191)) STORED;
ALTER TABLE `item_categories` ADD INDEX IF NOT EXISTS `idx_item_categories_id` (`id`);
ALTER TABLE `item_categories` ADD COLUMN IF NOT EXISTS `code` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.code'), 191)) STORED;
ALTER TABLE `item_categories` ADD INDEX IF NOT EXISTS `idx_item_categories_code` (`code`);
ALTER TABLE `item_categories` ADD COLUMN IF NOT EXISTS `is_active` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.is_active'), 191)) STORED;
ALTER TABLE `item_categories` ADD INDEX IF NOT EXISTS `idx_item_categories_is_active` (`is_active`);
ALTER TABLE `item_categories` ADD COLUMN IF NOT EXISTS `name` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.name'), 191)) STORED;
ALTER TABLE `item_categories` ADD INDEX IF NOT EXISTS `idx_item_categories_name` (`name`);

-- ---- item_warehouse (340 dokumen contoh) ----
CREATE TABLE IF NOT EXISTS `item_warehouse` (
  pk VARCHAR(64) NOT NULL PRIMARY KEY COMMENT 'doc.id atau UUID',
  doc LONGTEXT NOT NULL COMMENT 'Dokumen lengkap (JSON)' CHECK (JSON_VALID(doc)),
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  KEY idx_item_warehouse_created (created_at, pk)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Koleksi item_warehouse (ProcureFlow)';
ALTER TABLE `item_warehouse` ADD COLUMN IF NOT EXISTS `id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.id'), 191)) STORED;
ALTER TABLE `item_warehouse` ADD INDEX IF NOT EXISTS `idx_item_warehouse_id` (`id`);
ALTER TABLE `item_warehouse` ADD COLUMN IF NOT EXISTS `item_id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.item_id'), 191)) STORED;
ALTER TABLE `item_warehouse` ADD INDEX IF NOT EXISTS `idx_item_warehouse_item_id` (`item_id`);
ALTER TABLE `item_warehouse` ADD COLUMN IF NOT EXISTS `opening_updated_at` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.opening_updated_at'), 191)) STORED;
ALTER TABLE `item_warehouse` ADD INDEX IF NOT EXISTS `idx_item_warehouse_opening_updated_at` (`opening_updated_at`);
ALTER TABLE `item_warehouse` ADD COLUMN IF NOT EXISTS `warehouse_id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.warehouse_id'), 191)) STORED;
ALTER TABLE `item_warehouse` ADD INDEX IF NOT EXISTS `idx_item_warehouse_warehouse_id` (`warehouse_id`);
ALTER TABLE `item_warehouse` ADD COLUMN IF NOT EXISTS `current_stock` TEXT AS (JSON_VALUE(doc, '$.current_stock')) STORED;
ALTER TABLE `item_warehouse` ADD COLUMN IF NOT EXISTS `max_stock` TEXT AS (JSON_VALUE(doc, '$.max_stock')) STORED;
ALTER TABLE `item_warehouse` ADD COLUMN IF NOT EXISTS `min_stock` TEXT AS (JSON_VALUE(doc, '$.min_stock')) STORED;
ALTER TABLE `item_warehouse` ADD COLUMN IF NOT EXISTS `opening_average_cost` TEXT AS (JSON_VALUE(doc, '$.opening_average_cost')) STORED;
ALTER TABLE `item_warehouse` ADD COLUMN IF NOT EXISTS `opening_qty` TEXT AS (JSON_VALUE(doc, '$.opening_qty')) STORED;
ALTER TABLE `item_warehouse` ADD COLUMN IF NOT EXISTS `opening_value` TEXT AS (JSON_VALUE(doc, '$.opening_value')) STORED;

-- ---- items (949 dokumen contoh) ----
CREATE TABLE IF NOT EXISTS `items` (
  pk VARCHAR(64) NOT NULL PRIMARY KEY COMMENT 'doc.id atau UUID',
  doc LONGTEXT NOT NULL COMMENT 'Dokumen lengkap (JSON)' CHECK (JSON_VALID(doc)),
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  KEY idx_items_created (created_at, pk)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Koleksi items (ProcureFlow)';
ALTER TABLE `items` ADD COLUMN IF NOT EXISTS `id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.id'), 191)) STORED;
ALTER TABLE `items` ADD INDEX IF NOT EXISTS `idx_items_id` (`id`);
ALTER TABLE `items` ADD COLUMN IF NOT EXISTS `base_uom_id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.base_uom_id'), 191)) STORED;
ALTER TABLE `items` ADD INDEX IF NOT EXISTS `idx_items_base_uom_id` (`base_uom_id`);
ALTER TABLE `items` ADD COLUMN IF NOT EXISTS `category` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.category'), 191)) STORED;
ALTER TABLE `items` ADD INDEX IF NOT EXISTS `idx_items_category` (`category`);
ALTER TABLE `items` ADD COLUMN IF NOT EXISTS `category_id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.category_id'), 191)) STORED;
ALTER TABLE `items` ADD INDEX IF NOT EXISTS `idx_items_category_id` (`category_id`);
ALTER TABLE `items` ADD COLUMN IF NOT EXISTS `code` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.code'), 191)) STORED;
ALTER TABLE `items` ADD INDEX IF NOT EXISTS `idx_items_code` (`code`);
ALTER TABLE `items` ADD COLUMN IF NOT EXISTS `division_id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.division_id'), 191)) STORED;
ALTER TABLE `items` ADD INDEX IF NOT EXISTS `idx_items_division_id` (`division_id`);
ALTER TABLE `items` ADD COLUMN IF NOT EXISTS `is_active` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.is_active'), 191)) STORED;
ALTER TABLE `items` ADD INDEX IF NOT EXISTS `idx_items_is_active` (`is_active`);
ALTER TABLE `items` ADD COLUMN IF NOT EXISTS `name` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.name'), 191)) STORED;
ALTER TABLE `items` ADD INDEX IF NOT EXISTS `idx_items_name` (`name`);
ALTER TABLE `items` ADD COLUMN IF NOT EXISTS `unit` TEXT AS (JSON_VALUE(doc, '$.unit')) STORED;
ALTER TABLE `items` ADD COLUMN IF NOT EXISTS `alt_unit` TEXT AS (JSON_VALUE(doc, '$.alt_unit')) STORED;
ALTER TABLE `items` ADD COLUMN IF NOT EXISTS `brand` TEXT AS (JSON_VALUE(doc, '$.brand')) STORED;
ALTER TABLE `items` ADD COLUMN IF NOT EXISTS `alias` TEXT AS (JSON_VALUE(doc, '$.alias')) STORED;
ALTER TABLE `items` ADD COLUMN IF NOT EXISTS `part_number` TEXT AS (JSON_VALUE(doc, '$.part_number')) STORED;
ALTER TABLE `items` ADD COLUMN IF NOT EXISTS `spec` TEXT AS (JSON_VALUE(doc, '$.spec')) STORED;

-- ---- loan_lines (1 dokumen contoh) ----
CREATE TABLE IF NOT EXISTS `loan_lines` (
  pk VARCHAR(64) NOT NULL PRIMARY KEY COMMENT 'doc.id atau UUID',
  doc LONGTEXT NOT NULL COMMENT 'Dokumen lengkap (JSON)' CHECK (JSON_VALID(doc)),
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  KEY idx_loan_lines_created (created_at, pk)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Koleksi loan_lines (ProcureFlow)';
ALTER TABLE `loan_lines` ADD COLUMN IF NOT EXISTS `id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.id'), 191)) STORED;
ALTER TABLE `loan_lines` ADD INDEX IF NOT EXISTS `idx_loan_lines_id` (`id`);
ALTER TABLE `loan_lines` ADD COLUMN IF NOT EXISTS `base_uom_id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.base_uom_id'), 191)) STORED;
ALTER TABLE `loan_lines` ADD INDEX IF NOT EXISTS `idx_loan_lines_base_uom_id` (`base_uom_id`);
ALTER TABLE `loan_lines` ADD COLUMN IF NOT EXISTS `item_id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.item_id'), 191)) STORED;
ALTER TABLE `loan_lines` ADD INDEX IF NOT EXISTS `idx_loan_lines_item_id` (`item_id`);
ALTER TABLE `loan_lines` ADD COLUMN IF NOT EXISTS `loan_id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.loan_id'), 191)) STORED;
ALTER TABLE `loan_lines` ADD INDEX IF NOT EXISTS `idx_loan_lines_loan_id` (`loan_id`);
ALTER TABLE `loan_lines` ADD COLUMN IF NOT EXISTS `project_id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.project_id'), 191)) STORED;
ALTER TABLE `loan_lines` ADD INDEX IF NOT EXISTS `idx_loan_lines_project_id` (`project_id`);
ALTER TABLE `loan_lines` ADD COLUMN IF NOT EXISTS `unit_id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.unit_id'), 191)) STORED;
ALTER TABLE `loan_lines` ADD INDEX IF NOT EXISTS `idx_loan_lines_unit_id` (`unit_id`);
ALTER TABLE `loan_lines` ADD COLUMN IF NOT EXISTS `uom_id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.uom_id'), 191)) STORED;
ALTER TABLE `loan_lines` ADD INDEX IF NOT EXISTS `idx_loan_lines_uom_id` (`uom_id`);
ALTER TABLE `loan_lines` ADD COLUMN IF NOT EXISTS `qty` TEXT AS (JSON_VALUE(doc, '$.qty')) STORED;
ALTER TABLE `loan_lines` ADD COLUMN IF NOT EXISTS `returned` TEXT AS (JSON_VALUE(doc, '$.returned')) STORED;
ALTER TABLE `loan_lines` ADD COLUMN IF NOT EXISTS `unit` TEXT AS (JSON_VALUE(doc, '$.unit')) STORED;
ALTER TABLE `loan_lines` ADD COLUMN IF NOT EXISTS `notes` TEXT AS (JSON_VALUE(doc, '$.notes')) STORED;
ALTER TABLE `loan_lines` ADD COLUMN IF NOT EXISTS `base_qty` TEXT AS (JSON_VALUE(doc, '$.base_qty')) STORED;
ALTER TABLE `loan_lines` ADD COLUMN IF NOT EXISTS `base_unit` TEXT AS (JSON_VALUE(doc, '$.base_unit')) STORED;
ALTER TABLE `loan_lines` ADD COLUMN IF NOT EXISTS `conversion_factor` TEXT AS (JSON_VALUE(doc, '$.conversion_factor')) STORED;
ALTER TABLE `loan_lines` ADD COLUMN IF NOT EXISTS `display_price` TEXT AS (JSON_VALUE(doc, '$.display_price')) STORED;
ALTER TABLE `loan_lines` ADD COLUMN IF NOT EXISTS `display_qty` TEXT AS (JSON_VALUE(doc, '$.display_qty')) STORED;
ALTER TABLE `loan_lines` ADD COLUMN IF NOT EXISTS `display_unit` TEXT AS (JSON_VALUE(doc, '$.display_unit')) STORED;

-- ---- loan_return_lines (0 dokumen contoh) ----
CREATE TABLE IF NOT EXISTS `loan_return_lines` (
  pk VARCHAR(64) NOT NULL PRIMARY KEY COMMENT 'doc.id atau UUID',
  doc LONGTEXT NOT NULL COMMENT 'Dokumen lengkap (JSON)' CHECK (JSON_VALID(doc)),
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  KEY idx_loan_return_lines_created (created_at, pk)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Koleksi loan_return_lines (ProcureFlow)';
ALTER TABLE `loan_return_lines` ADD COLUMN IF NOT EXISTS `id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.id'), 191)) STORED;
ALTER TABLE `loan_return_lines` ADD INDEX IF NOT EXISTS `idx_loan_return_lines_id` (`id`);
ALTER TABLE `loan_return_lines` ADD COLUMN IF NOT EXISTS `code` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.code'), 191)) STORED;
ALTER TABLE `loan_return_lines` ADD INDEX IF NOT EXISTS `idx_loan_return_lines_code` (`code`);
ALTER TABLE `loan_return_lines` ADD COLUMN IF NOT EXISTS `no` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.no'), 191)) STORED;
ALTER TABLE `loan_return_lines` ADD INDEX IF NOT EXISTS `idx_loan_return_lines_no` (`no`);
ALTER TABLE `loan_return_lines` ADD COLUMN IF NOT EXISTS `status` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.status'), 191)) STORED;
ALTER TABLE `loan_return_lines` ADD INDEX IF NOT EXISTS `idx_loan_return_lines_status` (`status`);

-- ---- loan_returns (2 dokumen contoh) ----
CREATE TABLE IF NOT EXISTS `loan_returns` (
  pk VARCHAR(64) NOT NULL PRIMARY KEY COMMENT 'doc.id atau UUID',
  doc LONGTEXT NOT NULL COMMENT 'Dokumen lengkap (JSON)' CHECK (JSON_VALID(doc)),
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  KEY idx_loan_returns_created (created_at, pk)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Koleksi loan_returns (ProcureFlow)';
ALTER TABLE `loan_returns` ADD COLUMN IF NOT EXISTS `id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.id'), 191)) STORED;
ALTER TABLE `loan_returns` ADD INDEX IF NOT EXISTS `idx_loan_returns_id` (`id`);
ALTER TABLE `loan_returns` ADD COLUMN IF NOT EXISTS `created_by` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.created_by'), 191)) STORED;
ALTER TABLE `loan_returns` ADD INDEX IF NOT EXISTS `idx_loan_returns_created_by` (`created_by`);
ALTER TABLE `loan_returns` ADD COLUMN IF NOT EXISTS `date` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.date'), 191)) STORED;
ALTER TABLE `loan_returns` ADD INDEX IF NOT EXISTS `idx_loan_returns_date` (`date`);
ALTER TABLE `loan_returns` ADD COLUMN IF NOT EXISTS `loan_id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.loan_id'), 191)) STORED;
ALTER TABLE `loan_returns` ADD INDEX IF NOT EXISTS `idx_loan_returns_loan_id` (`loan_id`);
ALTER TABLE `loan_returns` ADD COLUMN IF NOT EXISTS `no` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.no'), 191)) STORED;
ALTER TABLE `loan_returns` ADD INDEX IF NOT EXISTS `idx_loan_returns_no` (`no`);
ALTER TABLE `loan_returns` ADD COLUMN IF NOT EXISTS `notes` TEXT AS (JSON_VALUE(doc, '$.notes')) STORED;

-- ---- loans (1 dokumen contoh) ----
CREATE TABLE IF NOT EXISTS `loans` (
  pk VARCHAR(64) NOT NULL PRIMARY KEY COMMENT 'doc.id atau UUID',
  doc LONGTEXT NOT NULL COMMENT 'Dokumen lengkap (JSON)' CHECK (JSON_VALID(doc)),
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  KEY idx_loans_created (created_at, pk)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Koleksi loans (ProcureFlow)';
ALTER TABLE `loans` ADD COLUMN IF NOT EXISTS `id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.id'), 191)) STORED;
ALTER TABLE `loans` ADD INDEX IF NOT EXISTS `idx_loans_id` (`id`);
ALTER TABLE `loans` ADD COLUMN IF NOT EXISTS `created_by` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.created_by'), 191)) STORED;
ALTER TABLE `loans` ADD INDEX IF NOT EXISTS `idx_loans_created_by` (`created_by`);
ALTER TABLE `loans` ADD COLUMN IF NOT EXISTS `date` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.date'), 191)) STORED;
ALTER TABLE `loans` ADD INDEX IF NOT EXISTS `idx_loans_date` (`date`);
ALTER TABLE `loans` ADD COLUMN IF NOT EXISTS `due_date` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.due_date'), 191)) STORED;
ALTER TABLE `loans` ADD INDEX IF NOT EXISTS `idx_loans_due_date` (`due_date`);
ALTER TABLE `loans` ADD COLUMN IF NOT EXISTS `from_warehouse_id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.from_warehouse_id'), 191)) STORED;
ALTER TABLE `loans` ADD INDEX IF NOT EXISTS `idx_loans_from_warehouse_id` (`from_warehouse_id`);
ALTER TABLE `loans` ADD COLUMN IF NOT EXISTS `no` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.no'), 191)) STORED;
ALTER TABLE `loans` ADD INDEX IF NOT EXISTS `idx_loans_no` (`no`);
ALTER TABLE `loans` ADD COLUMN IF NOT EXISTS `project_id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.project_id'), 191)) STORED;
ALTER TABLE `loans` ADD INDEX IF NOT EXISTS `idx_loans_project_id` (`project_id`);
ALTER TABLE `loans` ADD COLUMN IF NOT EXISTS `to_warehouse_id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.to_warehouse_id'), 191)) STORED;
ALTER TABLE `loans` ADD INDEX IF NOT EXISTS `idx_loans_to_warehouse_id` (`to_warehouse_id`);
ALTER TABLE `loans` ADD COLUMN IF NOT EXISTS `requester` TEXT AS (JSON_VALUE(doc, '$.requester')) STORED;
ALTER TABLE `loans` ADD COLUMN IF NOT EXISTS `notes` TEXT AS (JSON_VALUE(doc, '$.notes')) STORED;

-- ---- login_attempts (0 dokumen contoh) ----
CREATE TABLE IF NOT EXISTS `login_attempts` (
  pk VARCHAR(64) NOT NULL PRIMARY KEY COMMENT 'doc.id atau UUID',
  doc LONGTEXT NOT NULL COMMENT 'Dokumen lengkap (JSON)' CHECK (JSON_VALID(doc)),
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  KEY idx_login_attempts_created (created_at, pk)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Koleksi login_attempts (ProcureFlow)';
ALTER TABLE `login_attempts` ADD COLUMN IF NOT EXISTS `id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.id'), 191)) STORED;
ALTER TABLE `login_attempts` ADD INDEX IF NOT EXISTS `idx_login_attempts_id` (`id`);
ALTER TABLE `login_attempts` ADD COLUMN IF NOT EXISTS `code` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.code'), 191)) STORED;
ALTER TABLE `login_attempts` ADD INDEX IF NOT EXISTS `idx_login_attempts_code` (`code`);
ALTER TABLE `login_attempts` ADD COLUMN IF NOT EXISTS `no` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.no'), 191)) STORED;
ALTER TABLE `login_attempts` ADD INDEX IF NOT EXISTS `idx_login_attempts_no` (`no`);
ALTER TABLE `login_attempts` ADD COLUMN IF NOT EXISTS `status` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.status'), 191)) STORED;
ALTER TABLE `login_attempts` ADD INDEX IF NOT EXISTS `idx_login_attempts_status` (`status`);

-- ---- mi (0 dokumen contoh) ----
CREATE TABLE IF NOT EXISTS `mi` (
  pk VARCHAR(64) NOT NULL PRIMARY KEY COMMENT 'doc.id atau UUID',
  doc LONGTEXT NOT NULL COMMENT 'Dokumen lengkap (JSON)' CHECK (JSON_VALID(doc)),
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  KEY idx_mi_created (created_at, pk)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Koleksi mi (ProcureFlow)';
ALTER TABLE `mi` ADD COLUMN IF NOT EXISTS `id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.id'), 191)) STORED;
ALTER TABLE `mi` ADD INDEX IF NOT EXISTS `idx_mi_id` (`id`);
ALTER TABLE `mi` ADD COLUMN IF NOT EXISTS `code` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.code'), 191)) STORED;
ALTER TABLE `mi` ADD INDEX IF NOT EXISTS `idx_mi_code` (`code`);
ALTER TABLE `mi` ADD COLUMN IF NOT EXISTS `no` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.no'), 191)) STORED;
ALTER TABLE `mi` ADD INDEX IF NOT EXISTS `idx_mi_no` (`no`);
ALTER TABLE `mi` ADD COLUMN IF NOT EXISTS `status` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.status'), 191)) STORED;
ALTER TABLE `mi` ADD INDEX IF NOT EXISTS `idx_mi_status` (`status`);

-- ---- mi_lines (0 dokumen contoh) ----
CREATE TABLE IF NOT EXISTS `mi_lines` (
  pk VARCHAR(64) NOT NULL PRIMARY KEY COMMENT 'doc.id atau UUID',
  doc LONGTEXT NOT NULL COMMENT 'Dokumen lengkap (JSON)' CHECK (JSON_VALID(doc)),
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  KEY idx_mi_lines_created (created_at, pk)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Koleksi mi_lines (ProcureFlow)';
ALTER TABLE `mi_lines` ADD COLUMN IF NOT EXISTS `id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.id'), 191)) STORED;
ALTER TABLE `mi_lines` ADD INDEX IF NOT EXISTS `idx_mi_lines_id` (`id`);
ALTER TABLE `mi_lines` ADD COLUMN IF NOT EXISTS `code` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.code'), 191)) STORED;
ALTER TABLE `mi_lines` ADD INDEX IF NOT EXISTS `idx_mi_lines_code` (`code`);
ALTER TABLE `mi_lines` ADD COLUMN IF NOT EXISTS `no` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.no'), 191)) STORED;
ALTER TABLE `mi_lines` ADD INDEX IF NOT EXISTS `idx_mi_lines_no` (`no`);
ALTER TABLE `mi_lines` ADD COLUMN IF NOT EXISTS `status` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.status'), 191)) STORED;
ALTER TABLE `mi_lines` ADD INDEX IF NOT EXISTS `idx_mi_lines_status` (`status`);

-- ---- mro (6 dokumen contoh) ----
CREATE TABLE IF NOT EXISTS `mro` (
  pk VARCHAR(64) NOT NULL PRIMARY KEY COMMENT 'doc.id atau UUID',
  doc LONGTEXT NOT NULL COMMENT 'Dokumen lengkap (JSON)' CHECK (JSON_VALID(doc)),
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  KEY idx_mro_created (created_at, pk)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Koleksi mro (ProcureFlow)';
ALTER TABLE `mro` ADD COLUMN IF NOT EXISTS `id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.id'), 191)) STORED;
ALTER TABLE `mro` ADD INDEX IF NOT EXISTS `idx_mro_id` (`id`);
ALTER TABLE `mro` ADD COLUMN IF NOT EXISTS `approval_status` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.approval_status'), 191)) STORED;
ALTER TABLE `mro` ADD INDEX IF NOT EXISTS `idx_mro_approval_status` (`approval_status`);
ALTER TABLE `mro` ADD COLUMN IF NOT EXISTS `created_by` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.created_by'), 191)) STORED;
ALTER TABLE `mro` ADD INDEX IF NOT EXISTS `idx_mro_created_by` (`created_by`);
ALTER TABLE `mro` ADD COLUMN IF NOT EXISTS `date` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.date'), 191)) STORED;
ALTER TABLE `mro` ADD INDEX IF NOT EXISTS `idx_mro_date` (`date`);
ALTER TABLE `mro` ADD COLUMN IF NOT EXISTS `default_project_id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.default_project_id'), 191)) STORED;
ALTER TABLE `mro` ADD INDEX IF NOT EXISTS `idx_mro_default_project_id` (`default_project_id`);
ALTER TABLE `mro` ADD COLUMN IF NOT EXISTS `default_unit_id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.default_unit_id'), 191)) STORED;
ALTER TABLE `mro` ADD INDEX IF NOT EXISTS `idx_mro_default_unit_id` (`default_unit_id`);
ALTER TABLE `mro` ADD COLUMN IF NOT EXISTS `default_warehouse_id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.default_warehouse_id'), 191)) STORED;
ALTER TABLE `mro` ADD INDEX IF NOT EXISTS `idx_mro_default_warehouse_id` (`default_warehouse_id`);
ALTER TABLE `mro` ADD COLUMN IF NOT EXISTS `division_id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.division_id'), 191)) STORED;
ALTER TABLE `mro` ADD INDEX IF NOT EXISTS `idx_mro_division_id` (`division_id`);
ALTER TABLE `mro` ADD COLUMN IF NOT EXISTS `document_message_updated_at` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.document_message_updated_at'), 191)) STORED;
ALTER TABLE `mro` ADD INDEX IF NOT EXISTS `idx_mro_document_message_updated_at` (`document_message_updated_at`);
ALTER TABLE `mro` ADD COLUMN IF NOT EXISTS `document_message_updated_by` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.document_message_updated_by'), 191)) STORED;
ALTER TABLE `mro` ADD INDEX IF NOT EXISTS `idx_mro_document_message_updated_by` (`document_message_updated_by`);
ALTER TABLE `mro` ADD COLUMN IF NOT EXISTS `need_date` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.need_date'), 191)) STORED;
ALTER TABLE `mro` ADD INDEX IF NOT EXISTS `idx_mro_need_date` (`need_date`);
ALTER TABLE `mro` ADD COLUMN IF NOT EXISTS `no` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.no'), 191)) STORED;
ALTER TABLE `mro` ADD INDEX IF NOT EXISTS `idx_mro_no` (`no`);
ALTER TABLE `mro` ADD COLUMN IF NOT EXISTS `updated_by` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.updated_by'), 191)) STORED;
ALTER TABLE `mro` ADD INDEX IF NOT EXISTS `idx_mro_updated_by` (`updated_by`);
ALTER TABLE `mro` ADD COLUMN IF NOT EXISTS `requester` TEXT AS (JSON_VALUE(doc, '$.requester')) STORED;
ALTER TABLE `mro` ADD COLUMN IF NOT EXISTS `department` TEXT AS (JSON_VALUE(doc, '$.department')) STORED;
ALTER TABLE `mro` ADD COLUMN IF NOT EXISTS `notes` TEXT AS (JSON_VALUE(doc, '$.notes')) STORED;
ALTER TABLE `mro` ADD COLUMN IF NOT EXISTS `submitted` TEXT AS (JSON_VALUE(doc, '$.submitted')) STORED;
ALTER TABLE `mro` ADD COLUMN IF NOT EXISTS `cancelled` TEXT AS (JSON_VALUE(doc, '$.cancelled')) STORED;
ALTER TABLE `mro` ADD COLUMN IF NOT EXISTS `approval_mode` TEXT AS (JSON_VALUE(doc, '$.approval_mode')) STORED;
ALTER TABLE `mro` ADD COLUMN IF NOT EXISTS `document_message` TEXT AS (JSON_VALUE(doc, '$.document_message')) STORED;
ALTER TABLE `mro` ADD COLUMN IF NOT EXISTS `spk` TEXT AS (JSON_VALUE(doc, '$.spk')) STORED;

-- ---- mro_lines (9 dokumen contoh) ----
CREATE TABLE IF NOT EXISTS `mro_lines` (
  pk VARCHAR(64) NOT NULL PRIMARY KEY COMMENT 'doc.id atau UUID',
  doc LONGTEXT NOT NULL COMMENT 'Dokumen lengkap (JSON)' CHECK (JSON_VALID(doc)),
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  KEY idx_mro_lines_created (created_at, pk)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Koleksi mro_lines (ProcureFlow)';
ALTER TABLE `mro_lines` ADD COLUMN IF NOT EXISTS `id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.id'), 191)) STORED;
ALTER TABLE `mro_lines` ADD INDEX IF NOT EXISTS `idx_mro_lines_id` (`id`);
ALTER TABLE `mro_lines` ADD COLUMN IF NOT EXISTS `base_uom_id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.base_uom_id'), 191)) STORED;
ALTER TABLE `mro_lines` ADD INDEX IF NOT EXISTS `idx_mro_lines_base_uom_id` (`base_uom_id`);
ALTER TABLE `mro_lines` ADD COLUMN IF NOT EXISTS `item_id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.item_id'), 191)) STORED;
ALTER TABLE `mro_lines` ADD INDEX IF NOT EXISTS `idx_mro_lines_item_id` (`item_id`);
ALTER TABLE `mro_lines` ADD COLUMN IF NOT EXISTS `mro_id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.mro_id'), 191)) STORED;
ALTER TABLE `mro_lines` ADD INDEX IF NOT EXISTS `idx_mro_lines_mro_id` (`mro_id`);
ALTER TABLE `mro_lines` ADD COLUMN IF NOT EXISTS `project_id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.project_id'), 191)) STORED;
ALTER TABLE `mro_lines` ADD INDEX IF NOT EXISTS `idx_mro_lines_project_id` (`project_id`);
ALTER TABLE `mro_lines` ADD COLUMN IF NOT EXISTS `unit_id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.unit_id'), 191)) STORED;
ALTER TABLE `mro_lines` ADD INDEX IF NOT EXISTS `idx_mro_lines_unit_id` (`unit_id`);
ALTER TABLE `mro_lines` ADD COLUMN IF NOT EXISTS `uom_id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.uom_id'), 191)) STORED;
ALTER TABLE `mro_lines` ADD INDEX IF NOT EXISTS `idx_mro_lines_uom_id` (`uom_id`);
ALTER TABLE `mro_lines` ADD COLUMN IF NOT EXISTS `warehouse_id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.warehouse_id'), 191)) STORED;
ALTER TABLE `mro_lines` ADD INDEX IF NOT EXISTS `idx_mro_lines_warehouse_id` (`warehouse_id`);
ALTER TABLE `mro_lines` ADD COLUMN IF NOT EXISTS `qty` TEXT AS (JSON_VALUE(doc, '$.qty')) STORED;
ALTER TABLE `mro_lines` ADD COLUMN IF NOT EXISTS `unit` TEXT AS (JSON_VALUE(doc, '$.unit')) STORED;
ALTER TABLE `mro_lines` ADD COLUMN IF NOT EXISTS `notes` TEXT AS (JSON_VALUE(doc, '$.notes')) STORED;
ALTER TABLE `mro_lines` ADD COLUMN IF NOT EXISTS `base_qty` TEXT AS (JSON_VALUE(doc, '$.base_qty')) STORED;
ALTER TABLE `mro_lines` ADD COLUMN IF NOT EXISTS `base_unit` TEXT AS (JSON_VALUE(doc, '$.base_unit')) STORED;
ALTER TABLE `mro_lines` ADD COLUMN IF NOT EXISTS `conversion_factor` TEXT AS (JSON_VALUE(doc, '$.conversion_factor')) STORED;
ALTER TABLE `mro_lines` ADD COLUMN IF NOT EXISTS `display_price` TEXT AS (JSON_VALUE(doc, '$.display_price')) STORED;
ALTER TABLE `mro_lines` ADD COLUMN IF NOT EXISTS `display_qty` TEXT AS (JSON_VALUE(doc, '$.display_qty')) STORED;
ALTER TABLE `mro_lines` ADD COLUMN IF NOT EXISTS `display_unit` TEXT AS (JSON_VALUE(doc, '$.display_unit')) STORED;

-- ---- notifications (40 dokumen contoh) ----
CREATE TABLE IF NOT EXISTS `notifications` (
  pk VARCHAR(64) NOT NULL PRIMARY KEY COMMENT 'doc.id atau UUID',
  doc LONGTEXT NOT NULL COMMENT 'Dokumen lengkap (JSON)' CHECK (JSON_VALID(doc)),
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  KEY idx_notifications_created (created_at, pk)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Koleksi notifications (ProcureFlow)';
ALTER TABLE `notifications` ADD COLUMN IF NOT EXISTS `id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.id'), 191)) STORED;
ALTER TABLE `notifications` ADD INDEX IF NOT EXISTS `idx_notifications_id` (`id`);
ALTER TABLE `notifications` ADD COLUMN IF NOT EXISTS `at` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.at'), 191)) STORED;
ALTER TABLE `notifications` ADD INDEX IF NOT EXISTS `idx_notifications_at` (`at`);
ALTER TABLE `notifications` ADD COLUMN IF NOT EXISTS `category` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.category'), 191)) STORED;
ALTER TABLE `notifications` ADD INDEX IF NOT EXISTS `idx_notifications_category` (`category`);
ALTER TABLE `notifications` ADD COLUMN IF NOT EXISTS `title` TEXT AS (JSON_VALUE(doc, '$.title')) STORED;
ALTER TABLE `notifications` ADD COLUMN IF NOT EXISTS `message` TEXT AS (JSON_VALUE(doc, '$.message')) STORED;
ALTER TABLE `notifications` ADD COLUMN IF NOT EXISTS `division` TEXT AS (JSON_VALUE(doc, '$.division')) STORED;
ALTER TABLE `notifications` ADD COLUMN IF NOT EXISTS `read` TEXT AS (JSON_VALUE(doc, '$.read')) STORED;

-- ---- opening_inventory (337 dokumen contoh) ----
CREATE TABLE IF NOT EXISTS `opening_inventory` (
  pk VARCHAR(64) NOT NULL PRIMARY KEY COMMENT 'doc.id atau UUID',
  doc LONGTEXT NOT NULL COMMENT 'Dokumen lengkap (JSON)' CHECK (JSON_VALID(doc)),
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  KEY idx_opening_inventory_created (created_at, pk)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Koleksi opening_inventory (ProcureFlow)';
ALTER TABLE `opening_inventory` ADD COLUMN IF NOT EXISTS `id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.id'), 191)) STORED;
ALTER TABLE `opening_inventory` ADD INDEX IF NOT EXISTS `idx_opening_inventory_id` (`id`);
ALTER TABLE `opening_inventory` ADD COLUMN IF NOT EXISTS `base_uom_id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.base_uom_id'), 191)) STORED;
ALTER TABLE `opening_inventory` ADD INDEX IF NOT EXISTS `idx_opening_inventory_base_uom_id` (`base_uom_id`);
ALTER TABLE `opening_inventory` ADD COLUMN IF NOT EXISTS `created_by` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.created_by'), 191)) STORED;
ALTER TABLE `opening_inventory` ADD INDEX IF NOT EXISTS `idx_opening_inventory_created_by` (`created_by`);
ALTER TABLE `opening_inventory` ADD COLUMN IF NOT EXISTS `item_id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.item_id'), 191)) STORED;
ALTER TABLE `opening_inventory` ADD INDEX IF NOT EXISTS `idx_opening_inventory_item_id` (`item_id`);
ALTER TABLE `opening_inventory` ADD COLUMN IF NOT EXISTS `project_id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.project_id'), 191)) STORED;
ALTER TABLE `opening_inventory` ADD INDEX IF NOT EXISTS `idx_opening_inventory_project_id` (`project_id`);
ALTER TABLE `opening_inventory` ADD COLUMN IF NOT EXISTS `uom_id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.uom_id'), 191)) STORED;
ALTER TABLE `opening_inventory` ADD INDEX IF NOT EXISTS `idx_opening_inventory_uom_id` (`uom_id`);
ALTER TABLE `opening_inventory` ADD COLUMN IF NOT EXISTS `warehouse_id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.warehouse_id'), 191)) STORED;
ALTER TABLE `opening_inventory` ADD INDEX IF NOT EXISTS `idx_opening_inventory_warehouse_id` (`warehouse_id`);
ALTER TABLE `opening_inventory` ADD COLUMN IF NOT EXISTS `item_code` TEXT AS (JSON_VALUE(doc, '$.item_code')) STORED;
ALTER TABLE `opening_inventory` ADD COLUMN IF NOT EXISTS `item_name` TEXT AS (JSON_VALUE(doc, '$.item_name')) STORED;
ALTER TABLE `opening_inventory` ADD COLUMN IF NOT EXISTS `warehouse_code` TEXT AS (JSON_VALUE(doc, '$.warehouse_code')) STORED;
ALTER TABLE `opening_inventory` ADD COLUMN IF NOT EXISTS `project_code` TEXT AS (JSON_VALUE(doc, '$.project_code')) STORED;
ALTER TABLE `opening_inventory` ADD COLUMN IF NOT EXISTS `uom_code` TEXT AS (JSON_VALUE(doc, '$.uom_code')) STORED;
ALTER TABLE `opening_inventory` ADD COLUMN IF NOT EXISTS `display_unit` TEXT AS (JSON_VALUE(doc, '$.display_unit')) STORED;
ALTER TABLE `opening_inventory` ADD COLUMN IF NOT EXISTS `base_unit` TEXT AS (JSON_VALUE(doc, '$.base_unit')) STORED;
ALTER TABLE `opening_inventory` ADD COLUMN IF NOT EXISTS `conversion_factor` TEXT AS (JSON_VALUE(doc, '$.conversion_factor')) STORED;
ALTER TABLE `opening_inventory` ADD COLUMN IF NOT EXISTS `display_qty` TEXT AS (JSON_VALUE(doc, '$.display_qty')) STORED;
ALTER TABLE `opening_inventory` ADD COLUMN IF NOT EXISTS `base_qty` TEXT AS (JSON_VALUE(doc, '$.base_qty')) STORED;
ALTER TABLE `opening_inventory` ADD COLUMN IF NOT EXISTS `purchase_price` TEXT AS (JSON_VALUE(doc, '$.purchase_price')) STORED;
ALTER TABLE `opening_inventory` ADD COLUMN IF NOT EXISTS `base_unit_cost` TEXT AS (JSON_VALUE(doc, '$.base_unit_cost')) STORED;
ALTER TABLE `opening_inventory` ADD COLUMN IF NOT EXISTS `opening_value` TEXT AS (JSON_VALUE(doc, '$.opening_value')) STORED;
ALTER TABLE `opening_inventory` ADD COLUMN IF NOT EXISTS `source_item_name` TEXT AS (JSON_VALUE(doc, '$.source_item_name')) STORED;

-- ---- opname (0 dokumen contoh) ----
CREATE TABLE IF NOT EXISTS `opname` (
  pk VARCHAR(64) NOT NULL PRIMARY KEY COMMENT 'doc.id atau UUID',
  doc LONGTEXT NOT NULL COMMENT 'Dokumen lengkap (JSON)' CHECK (JSON_VALID(doc)),
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  KEY idx_opname_created (created_at, pk)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Koleksi opname (ProcureFlow)';
ALTER TABLE `opname` ADD COLUMN IF NOT EXISTS `id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.id'), 191)) STORED;
ALTER TABLE `opname` ADD INDEX IF NOT EXISTS `idx_opname_id` (`id`);
ALTER TABLE `opname` ADD COLUMN IF NOT EXISTS `code` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.code'), 191)) STORED;
ALTER TABLE `opname` ADD INDEX IF NOT EXISTS `idx_opname_code` (`code`);
ALTER TABLE `opname` ADD COLUMN IF NOT EXISTS `no` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.no'), 191)) STORED;
ALTER TABLE `opname` ADD INDEX IF NOT EXISTS `idx_opname_no` (`no`);
ALTER TABLE `opname` ADD COLUMN IF NOT EXISTS `status` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.status'), 191)) STORED;
ALTER TABLE `opname` ADD INDEX IF NOT EXISTS `idx_opname_status` (`status`);

-- ---- opname_lines (0 dokumen contoh) ----
CREATE TABLE IF NOT EXISTS `opname_lines` (
  pk VARCHAR(64) NOT NULL PRIMARY KEY COMMENT 'doc.id atau UUID',
  doc LONGTEXT NOT NULL COMMENT 'Dokumen lengkap (JSON)' CHECK (JSON_VALID(doc)),
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  KEY idx_opname_lines_created (created_at, pk)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Koleksi opname_lines (ProcureFlow)';
ALTER TABLE `opname_lines` ADD COLUMN IF NOT EXISTS `id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.id'), 191)) STORED;
ALTER TABLE `opname_lines` ADD INDEX IF NOT EXISTS `idx_opname_lines_id` (`id`);
ALTER TABLE `opname_lines` ADD COLUMN IF NOT EXISTS `code` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.code'), 191)) STORED;
ALTER TABLE `opname_lines` ADD INDEX IF NOT EXISTS `idx_opname_lines_code` (`code`);
ALTER TABLE `opname_lines` ADD COLUMN IF NOT EXISTS `no` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.no'), 191)) STORED;
ALTER TABLE `opname_lines` ADD INDEX IF NOT EXISTS `idx_opname_lines_no` (`no`);
ALTER TABLE `opname_lines` ADD COLUMN IF NOT EXISTS `status` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.status'), 191)) STORED;
ALTER TABLE `opname_lines` ADD INDEX IF NOT EXISTS `idx_opname_lines_status` (`status`);

-- ---- po (3 dokumen contoh) ----
CREATE TABLE IF NOT EXISTS `po` (
  pk VARCHAR(64) NOT NULL PRIMARY KEY COMMENT 'doc.id atau UUID',
  doc LONGTEXT NOT NULL COMMENT 'Dokumen lengkap (JSON)' CHECK (JSON_VALID(doc)),
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  KEY idx_po_created (created_at, pk)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Koleksi po (ProcureFlow)';
ALTER TABLE `po` ADD COLUMN IF NOT EXISTS `id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.id'), 191)) STORED;
ALTER TABLE `po` ADD INDEX IF NOT EXISTS `idx_po_id` (`id`);
ALTER TABLE `po` ADD COLUMN IF NOT EXISTS `approval_status` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.approval_status'), 191)) STORED;
ALTER TABLE `po` ADD INDEX IF NOT EXISTS `idx_po_approval_status` (`approval_status`);
ALTER TABLE `po` ADD COLUMN IF NOT EXISTS `buyer_contact_division_id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.buyer_contact_division_id'), 191)) STORED;
ALTER TABLE `po` ADD INDEX IF NOT EXISTS `idx_po_buyer_contact_division_id` (`buyer_contact_division_id`);
ALTER TABLE `po` ADD COLUMN IF NOT EXISTS `buyer_contact_id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.buyer_contact_id'), 191)) STORED;
ALTER TABLE `po` ADD INDEX IF NOT EXISTS `idx_po_buyer_contact_id` (`buyer_contact_id`);
ALTER TABLE `po` ADD COLUMN IF NOT EXISTS `created_by` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.created_by'), 191)) STORED;
ALTER TABLE `po` ADD INDEX IF NOT EXISTS `idx_po_created_by` (`created_by`);
ALTER TABLE `po` ADD COLUMN IF NOT EXISTS `date` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.date'), 191)) STORED;
ALTER TABLE `po` ADD INDEX IF NOT EXISTS `idx_po_date` (`date`);
ALTER TABLE `po` ADD COLUMN IF NOT EXISTS `default_project_id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.default_project_id'), 191)) STORED;
ALTER TABLE `po` ADD INDEX IF NOT EXISTS `idx_po_default_project_id` (`default_project_id`);
ALTER TABLE `po` ADD COLUMN IF NOT EXISTS `default_tax_id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.default_tax_id'), 191)) STORED;
ALTER TABLE `po` ADD INDEX IF NOT EXISTS `idx_po_default_tax_id` (`default_tax_id`);
ALTER TABLE `po` ADD COLUMN IF NOT EXISTS `default_unit_id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.default_unit_id'), 191)) STORED;
ALTER TABLE `po` ADD INDEX IF NOT EXISTS `idx_po_default_unit_id` (`default_unit_id`);
ALTER TABLE `po` ADD COLUMN IF NOT EXISTS `default_warehouse_id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.default_warehouse_id'), 191)) STORED;
ALTER TABLE `po` ADD INDEX IF NOT EXISTS `idx_po_default_warehouse_id` (`default_warehouse_id`);
ALTER TABLE `po` ADD COLUMN IF NOT EXISTS `division_id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.division_id'), 191)) STORED;
ALTER TABLE `po` ADD INDEX IF NOT EXISTS `idx_po_division_id` (`division_id`);
ALTER TABLE `po` ADD COLUMN IF NOT EXISTS `document_message_updated_at` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.document_message_updated_at'), 191)) STORED;
ALTER TABLE `po` ADD INDEX IF NOT EXISTS `idx_po_document_message_updated_at` (`document_message_updated_at`);
ALTER TABLE `po` ADD COLUMN IF NOT EXISTS `document_message_updated_by` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.document_message_updated_by'), 191)) STORED;
ALTER TABLE `po` ADD INDEX IF NOT EXISTS `idx_po_document_message_updated_by` (`document_message_updated_by`);
ALTER TABLE `po` ADD COLUMN IF NOT EXISTS `no` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.no'), 191)) STORED;
ALTER TABLE `po` ADD INDEX IF NOT EXISTS `idx_po_no` (`no`);
ALTER TABLE `po` ADD COLUMN IF NOT EXISTS `status` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.status'), 191)) STORED;
ALTER TABLE `po` ADD INDEX IF NOT EXISTS `idx_po_status` (`status`);
ALTER TABLE `po` ADD COLUMN IF NOT EXISTS `supplier_bank_account_no` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.supplier_bank_account_no'), 191)) STORED;
ALTER TABLE `po` ADD INDEX IF NOT EXISTS `idx_po_supplier_bank_account_no` (`supplier_bank_account_no`);
ALTER TABLE `po` ADD COLUMN IF NOT EXISTS `supplier_bank_id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.supplier_bank_id'), 191)) STORED;
ALTER TABLE `po` ADD INDEX IF NOT EXISTS `idx_po_supplier_bank_id` (`supplier_bank_id`);
ALTER TABLE `po` ADD COLUMN IF NOT EXISTS `supplier_category_id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.supplier_category_id'), 191)) STORED;
ALTER TABLE `po` ADD INDEX IF NOT EXISTS `idx_po_supplier_category_id` (`supplier_category_id`);
ALTER TABLE `po` ADD COLUMN IF NOT EXISTS `supplier_id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.supplier_id'), 191)) STORED;
ALTER TABLE `po` ADD INDEX IF NOT EXISTS `idx_po_supplier_id` (`supplier_id`);
ALTER TABLE `po` ADD COLUMN IF NOT EXISTS `updated_by` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.updated_by'), 191)) STORED;
ALTER TABLE `po` ADD INDEX IF NOT EXISTS `idx_po_updated_by` (`updated_by`);
ALTER TABLE `po` ADD COLUMN IF NOT EXISTS `payment_term` TEXT AS (JSON_VALUE(doc, '$.payment_term')) STORED;
ALTER TABLE `po` ADD COLUMN IF NOT EXISTS `eta` TEXT AS (JSON_VALUE(doc, '$.eta')) STORED;
ALTER TABLE `po` ADD COLUMN IF NOT EXISTS `currency` TEXT AS (JSON_VALUE(doc, '$.currency')) STORED;
ALTER TABLE `po` ADD COLUMN IF NOT EXISTS `tax_pct` TEXT AS (JSON_VALUE(doc, '$.tax_pct')) STORED;
ALTER TABLE `po` ADD COLUMN IF NOT EXISTS `supplier_notes` TEXT AS (JSON_VALUE(doc, '$.supplier_notes')) STORED;
ALTER TABLE `po` ADD COLUMN IF NOT EXISTS `internal_notes` TEXT AS (JSON_VALUE(doc, '$.internal_notes')) STORED;
ALTER TABLE `po` ADD COLUMN IF NOT EXISTS `grand_total` TEXT AS (JSON_VALUE(doc, '$.grand_total')) STORED;
ALTER TABLE `po` ADD COLUMN IF NOT EXISTS `cancelled` TEXT AS (JSON_VALUE(doc, '$.cancelled')) STORED;
ALTER TABLE `po` ADD COLUMN IF NOT EXISTS `delivery_term` TEXT AS (JSON_VALUE(doc, '$.delivery_term')) STORED;
ALTER TABLE `po` ADD COLUMN IF NOT EXISTS `spk` TEXT AS (JSON_VALUE(doc, '$.spk')) STORED;
ALTER TABLE `po` ADD COLUMN IF NOT EXISTS `tax_inclusive` TEXT AS (JSON_VALUE(doc, '$.tax_inclusive')) STORED;
ALTER TABLE `po` ADD COLUMN IF NOT EXISTS `buyer_contact_email` TEXT AS (JSON_VALUE(doc, '$.buyer_contact_email')) STORED;
ALTER TABLE `po` ADD COLUMN IF NOT EXISTS `buyer_contact_name` TEXT AS (JSON_VALUE(doc, '$.buyer_contact_name')) STORED;
ALTER TABLE `po` ADD COLUMN IF NOT EXISTS `buyer_contact_phone` TEXT AS (JSON_VALUE(doc, '$.buyer_contact_phone')) STORED;
ALTER TABLE `po` ADD COLUMN IF NOT EXISTS `buyer_contact_position` TEXT AS (JSON_VALUE(doc, '$.buyer_contact_position')) STORED;
ALTER TABLE `po` ADD COLUMN IF NOT EXISTS `supplier_ref` TEXT AS (JSON_VALUE(doc, '$.supplier_ref')) STORED;
ALTER TABLE `po` ADD COLUMN IF NOT EXISTS `document_message` TEXT AS (JSON_VALUE(doc, '$.document_message')) STORED;
ALTER TABLE `po` ADD COLUMN IF NOT EXISTS `approval_mode` TEXT AS (JSON_VALUE(doc, '$.approval_mode')) STORED;
ALTER TABLE `po` ADD COLUMN IF NOT EXISTS `supplier_bank_account_name` TEXT AS (JSON_VALUE(doc, '$.supplier_bank_account_name')) STORED;
ALTER TABLE `po` ADD COLUMN IF NOT EXISTS `supplier_bank_currency` TEXT AS (JSON_VALUE(doc, '$.supplier_bank_currency')) STORED;

-- ---- po_approvals (3 dokumen contoh) ----
CREATE TABLE IF NOT EXISTS `po_approvals` (
  pk VARCHAR(64) NOT NULL PRIMARY KEY COMMENT 'doc.id atau UUID',
  doc LONGTEXT NOT NULL COMMENT 'Dokumen lengkap (JSON)' CHECK (JSON_VALID(doc)),
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  KEY idx_po_approvals_created (created_at, pk)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Koleksi po_approvals (ProcureFlow)';
ALTER TABLE `po_approvals` ADD COLUMN IF NOT EXISTS `id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.id'), 191)) STORED;
ALTER TABLE `po_approvals` ADD INDEX IF NOT EXISTS `idx_po_approvals_id` (`id`);
ALTER TABLE `po_approvals` ADD COLUMN IF NOT EXISTS `acted_at` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.acted_at'), 191)) STORED;
ALTER TABLE `po_approvals` ADD INDEX IF NOT EXISTS `idx_po_approvals_acted_at` (`acted_at`);
ALTER TABLE `po_approvals` ADD COLUMN IF NOT EXISTS `acted_by` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.acted_by'), 191)) STORED;
ALTER TABLE `po_approvals` ADD INDEX IF NOT EXISTS `idx_po_approvals_acted_by` (`acted_by`);
ALTER TABLE `po_approvals` ADD COLUMN IF NOT EXISTS `approver_user_id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.approver_user_id'), 191)) STORED;
ALTER TABLE `po_approvals` ADD INDEX IF NOT EXISTS `idx_po_approvals_approver_user_id` (`approver_user_id`);
ALTER TABLE `po_approvals` ADD COLUMN IF NOT EXISTS `po_id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.po_id'), 191)) STORED;
ALTER TABLE `po_approvals` ADD INDEX IF NOT EXISTS `idx_po_approvals_po_id` (`po_id`);
ALTER TABLE `po_approvals` ADD COLUMN IF NOT EXISTS `role` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.role'), 191)) STORED;
ALTER TABLE `po_approvals` ADD INDEX IF NOT EXISTS `idx_po_approvals_role` (`role`);
ALTER TABLE `po_approvals` ADD COLUMN IF NOT EXISTS `status` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.status'), 191)) STORED;
ALTER TABLE `po_approvals` ADD INDEX IF NOT EXISTS `idx_po_approvals_status` (`status`);
ALTER TABLE `po_approvals` ADD COLUMN IF NOT EXISTS `seq` TEXT AS (JSON_VALUE(doc, '$.seq')) STORED;
ALTER TABLE `po_approvals` ADD COLUMN IF NOT EXISTS `level` TEXT AS (JSON_VALUE(doc, '$.level')) STORED;
ALTER TABLE `po_approvals` ADD COLUMN IF NOT EXISTS `approver_email` TEXT AS (JSON_VALUE(doc, '$.approver_email')) STORED;
ALTER TABLE `po_approvals` ADD COLUMN IF NOT EXISTS `approver_name` TEXT AS (JSON_VALUE(doc, '$.approver_name')) STORED;
ALTER TABLE `po_approvals` ADD COLUMN IF NOT EXISTS `acted_by_email` TEXT AS (JSON_VALUE(doc, '$.acted_by_email')) STORED;
ALTER TABLE `po_approvals` ADD COLUMN IF NOT EXISTS `note` TEXT AS (JSON_VALUE(doc, '$.note')) STORED;

-- ---- po_lines (5 dokumen contoh) ----
CREATE TABLE IF NOT EXISTS `po_lines` (
  pk VARCHAR(64) NOT NULL PRIMARY KEY COMMENT 'doc.id atau UUID',
  doc LONGTEXT NOT NULL COMMENT 'Dokumen lengkap (JSON)' CHECK (JSON_VALID(doc)),
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  KEY idx_po_lines_created (created_at, pk)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Koleksi po_lines (ProcureFlow)';
ALTER TABLE `po_lines` ADD COLUMN IF NOT EXISTS `id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.id'), 191)) STORED;
ALTER TABLE `po_lines` ADD INDEX IF NOT EXISTS `idx_po_lines_id` (`id`);
ALTER TABLE `po_lines` ADD COLUMN IF NOT EXISTS `base_uom_id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.base_uom_id'), 191)) STORED;
ALTER TABLE `po_lines` ADD INDEX IF NOT EXISTS `idx_po_lines_base_uom_id` (`base_uom_id`);
ALTER TABLE `po_lines` ADD COLUMN IF NOT EXISTS `item_id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.item_id'), 191)) STORED;
ALTER TABLE `po_lines` ADD INDEX IF NOT EXISTS `idx_po_lines_item_id` (`item_id`);
ALTER TABLE `po_lines` ADD COLUMN IF NOT EXISTS `po_id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.po_id'), 191)) STORED;
ALTER TABLE `po_lines` ADD INDEX IF NOT EXISTS `idx_po_lines_po_id` (`po_id`);
ALTER TABLE `po_lines` ADD COLUMN IF NOT EXISTS `project_id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.project_id'), 191)) STORED;
ALTER TABLE `po_lines` ADD INDEX IF NOT EXISTS `idx_po_lines_project_id` (`project_id`);
ALTER TABLE `po_lines` ADD COLUMN IF NOT EXISTS `tax_id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.tax_id'), 191)) STORED;
ALTER TABLE `po_lines` ADD INDEX IF NOT EXISTS `idx_po_lines_tax_id` (`tax_id`);
ALTER TABLE `po_lines` ADD COLUMN IF NOT EXISTS `unit_id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.unit_id'), 191)) STORED;
ALTER TABLE `po_lines` ADD INDEX IF NOT EXISTS `idx_po_lines_unit_id` (`unit_id`);
ALTER TABLE `po_lines` ADD COLUMN IF NOT EXISTS `uom_id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.uom_id'), 191)) STORED;
ALTER TABLE `po_lines` ADD INDEX IF NOT EXISTS `idx_po_lines_uom_id` (`uom_id`);
ALTER TABLE `po_lines` ADD COLUMN IF NOT EXISTS `warehouse_id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.warehouse_id'), 191)) STORED;
ALTER TABLE `po_lines` ADD INDEX IF NOT EXISTS `idx_po_lines_warehouse_id` (`warehouse_id`);
ALTER TABLE `po_lines` ADD COLUMN IF NOT EXISTS `qty` TEXT AS (JSON_VALUE(doc, '$.qty')) STORED;
ALTER TABLE `po_lines` ADD COLUMN IF NOT EXISTS `unit` TEXT AS (JSON_VALUE(doc, '$.unit')) STORED;
ALTER TABLE `po_lines` ADD COLUMN IF NOT EXISTS `spk` TEXT AS (JSON_VALUE(doc, '$.spk')) STORED;
ALTER TABLE `po_lines` ADD COLUMN IF NOT EXISTS `price` TEXT AS (JSON_VALUE(doc, '$.price')) STORED;
ALTER TABLE `po_lines` ADD COLUMN IF NOT EXISTS `discount` TEXT AS (JSON_VALUE(doc, '$.discount')) STORED;
ALTER TABLE `po_lines` ADD COLUMN IF NOT EXISTS `tax` TEXT AS (JSON_VALUE(doc, '$.tax')) STORED;
ALTER TABLE `po_lines` ADD COLUMN IF NOT EXISTS `tax_name` TEXT AS (JSON_VALUE(doc, '$.tax_name')) STORED;
ALTER TABLE `po_lines` ADD COLUMN IF NOT EXISTS `notes` TEXT AS (JSON_VALUE(doc, '$.notes')) STORED;
ALTER TABLE `po_lines` ADD COLUMN IF NOT EXISTS `display_qty` TEXT AS (JSON_VALUE(doc, '$.display_qty')) STORED;
ALTER TABLE `po_lines` ADD COLUMN IF NOT EXISTS `conversion_factor` TEXT AS (JSON_VALUE(doc, '$.conversion_factor')) STORED;
ALTER TABLE `po_lines` ADD COLUMN IF NOT EXISTS `display_unit` TEXT AS (JSON_VALUE(doc, '$.display_unit')) STORED;
ALTER TABLE `po_lines` ADD COLUMN IF NOT EXISTS `base_qty` TEXT AS (JSON_VALUE(doc, '$.base_qty')) STORED;
ALTER TABLE `po_lines` ADD COLUMN IF NOT EXISTS `base_unit` TEXT AS (JSON_VALUE(doc, '$.base_unit')) STORED;
ALTER TABLE `po_lines` ADD COLUMN IF NOT EXISTS `display_price` TEXT AS (JSON_VALUE(doc, '$.display_price')) STORED;
ALTER TABLE `po_lines` ADD COLUMN IF NOT EXISTS `dpp` TEXT AS (JSON_VALUE(doc, '$.dpp')) STORED;
ALTER TABLE `po_lines` ADD COLUMN IF NOT EXISTS `gross` TEXT AS (JSON_VALUE(doc, '$.gross')) STORED;
ALTER TABLE `po_lines` ADD COLUMN IF NOT EXISTS `tax_amount` TEXT AS (JSON_VALUE(doc, '$.tax_amount')) STORED;
ALTER TABLE `po_lines` ADD COLUMN IF NOT EXISTS `tax_inclusive` TEXT AS (JSON_VALUE(doc, '$.tax_inclusive')) STORED;
ALTER TABLE `po_lines` ADD COLUMN IF NOT EXISTS `total` TEXT AS (JSON_VALUE(doc, '$.total')) STORED;
ALTER TABLE `po_lines` ADD COLUMN IF NOT EXISTS `tax_rate` TEXT AS (JSON_VALUE(doc, '$.tax_rate')) STORED;

-- ---- print_templates (0 dokumen contoh) ----
CREATE TABLE IF NOT EXISTS `print_templates` (
  pk VARCHAR(64) NOT NULL PRIMARY KEY COMMENT 'doc.id atau UUID',
  doc LONGTEXT NOT NULL COMMENT 'Dokumen lengkap (JSON)' CHECK (JSON_VALID(doc)),
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  KEY idx_print_templates_created (created_at, pk)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Koleksi print_templates (ProcureFlow)';
ALTER TABLE `print_templates` ADD COLUMN IF NOT EXISTS `id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.id'), 191)) STORED;
ALTER TABLE `print_templates` ADD INDEX IF NOT EXISTS `idx_print_templates_id` (`id`);
ALTER TABLE `print_templates` ADD COLUMN IF NOT EXISTS `code` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.code'), 191)) STORED;
ALTER TABLE `print_templates` ADD INDEX IF NOT EXISTS `idx_print_templates_code` (`code`);
ALTER TABLE `print_templates` ADD COLUMN IF NOT EXISTS `no` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.no'), 191)) STORED;
ALTER TABLE `print_templates` ADD INDEX IF NOT EXISTS `idx_print_templates_no` (`no`);
ALTER TABLE `print_templates` ADD COLUMN IF NOT EXISTS `status` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.status'), 191)) STORED;
ALTER TABLE `print_templates` ADD INDEX IF NOT EXISTS `idx_print_templates_status` (`status`);

-- ---- projects (13 dokumen contoh) ----
CREATE TABLE IF NOT EXISTS `projects` (
  pk VARCHAR(64) NOT NULL PRIMARY KEY COMMENT 'doc.id atau UUID',
  doc LONGTEXT NOT NULL COMMENT 'Dokumen lengkap (JSON)' CHECK (JSON_VALID(doc)),
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  KEY idx_projects_created (created_at, pk)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Koleksi projects (ProcureFlow)';
ALTER TABLE `projects` ADD COLUMN IF NOT EXISTS `id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.id'), 191)) STORED;
ALTER TABLE `projects` ADD INDEX IF NOT EXISTS `idx_projects_id` (`id`);
ALTER TABLE `projects` ADD COLUMN IF NOT EXISTS `code` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.code'), 191)) STORED;
ALTER TABLE `projects` ADD INDEX IF NOT EXISTS `idx_projects_code` (`code`);
ALTER TABLE `projects` ADD COLUMN IF NOT EXISTS `is_active` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.is_active'), 191)) STORED;
ALTER TABLE `projects` ADD INDEX IF NOT EXISTS `idx_projects_is_active` (`is_active`);
ALTER TABLE `projects` ADD COLUMN IF NOT EXISTS `name` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.name'), 191)) STORED;
ALTER TABLE `projects` ADD INDEX IF NOT EXISTS `idx_projects_name` (`name`);

-- ---- ro (1 dokumen contoh) ----
CREATE TABLE IF NOT EXISTS `ro` (
  pk VARCHAR(64) NOT NULL PRIMARY KEY COMMENT 'doc.id atau UUID',
  doc LONGTEXT NOT NULL COMMENT 'Dokumen lengkap (JSON)' CHECK (JSON_VALID(doc)),
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  KEY idx_ro_created (created_at, pk)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Koleksi ro (ProcureFlow)';
ALTER TABLE `ro` ADD COLUMN IF NOT EXISTS `id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.id'), 191)) STORED;
ALTER TABLE `ro` ADD INDEX IF NOT EXISTS `idx_ro_id` (`id`);
ALTER TABLE `ro` ADD COLUMN IF NOT EXISTS `approval_status` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.approval_status'), 191)) STORED;
ALTER TABLE `ro` ADD INDEX IF NOT EXISTS `idx_ro_approval_status` (`approval_status`);
ALTER TABLE `ro` ADD COLUMN IF NOT EXISTS `created_by` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.created_by'), 191)) STORED;
ALTER TABLE `ro` ADD INDEX IF NOT EXISTS `idx_ro_created_by` (`created_by`);
ALTER TABLE `ro` ADD COLUMN IF NOT EXISTS `date` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.date'), 191)) STORED;
ALTER TABLE `ro` ADD INDEX IF NOT EXISTS `idx_ro_date` (`date`);
ALTER TABLE `ro` ADD COLUMN IF NOT EXISTS `default_project_id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.default_project_id'), 191)) STORED;
ALTER TABLE `ro` ADD INDEX IF NOT EXISTS `idx_ro_default_project_id` (`default_project_id`);
ALTER TABLE `ro` ADD COLUMN IF NOT EXISTS `default_unit_id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.default_unit_id'), 191)) STORED;
ALTER TABLE `ro` ADD INDEX IF NOT EXISTS `idx_ro_default_unit_id` (`default_unit_id`);
ALTER TABLE `ro` ADD COLUMN IF NOT EXISTS `default_warehouse_id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.default_warehouse_id'), 191)) STORED;
ALTER TABLE `ro` ADD INDEX IF NOT EXISTS `idx_ro_default_warehouse_id` (`default_warehouse_id`);
ALTER TABLE `ro` ADD COLUMN IF NOT EXISTS `division_id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.division_id'), 191)) STORED;
ALTER TABLE `ro` ADD INDEX IF NOT EXISTS `idx_ro_division_id` (`division_id`);
ALTER TABLE `ro` ADD COLUMN IF NOT EXISTS `document_message_updated_at` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.document_message_updated_at'), 191)) STORED;
ALTER TABLE `ro` ADD INDEX IF NOT EXISTS `idx_ro_document_message_updated_at` (`document_message_updated_at`);
ALTER TABLE `ro` ADD COLUMN IF NOT EXISTS `document_message_updated_by` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.document_message_updated_by'), 191)) STORED;
ALTER TABLE `ro` ADD INDEX IF NOT EXISTS `idx_ro_document_message_updated_by` (`document_message_updated_by`);
ALTER TABLE `ro` ADD COLUMN IF NOT EXISTS `need_date` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.need_date'), 191)) STORED;
ALTER TABLE `ro` ADD INDEX IF NOT EXISTS `idx_ro_need_date` (`need_date`);
ALTER TABLE `ro` ADD COLUMN IF NOT EXISTS `no` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.no'), 191)) STORED;
ALTER TABLE `ro` ADD INDEX IF NOT EXISTS `idx_ro_no` (`no`);
ALTER TABLE `ro` ADD COLUMN IF NOT EXISTS `requester` TEXT AS (JSON_VALUE(doc, '$.requester')) STORED;
ALTER TABLE `ro` ADD COLUMN IF NOT EXISTS `notes` TEXT AS (JSON_VALUE(doc, '$.notes')) STORED;
ALTER TABLE `ro` ADD COLUMN IF NOT EXISTS `submitted` TEXT AS (JSON_VALUE(doc, '$.submitted')) STORED;
ALTER TABLE `ro` ADD COLUMN IF NOT EXISTS `cancelled` TEXT AS (JSON_VALUE(doc, '$.cancelled')) STORED;
ALTER TABLE `ro` ADD COLUMN IF NOT EXISTS `department` TEXT AS (JSON_VALUE(doc, '$.department')) STORED;
ALTER TABLE `ro` ADD COLUMN IF NOT EXISTS `spk` TEXT AS (JSON_VALUE(doc, '$.spk')) STORED;
ALTER TABLE `ro` ADD COLUMN IF NOT EXISTS `document_message` TEXT AS (JSON_VALUE(doc, '$.document_message')) STORED;
ALTER TABLE `ro` ADD COLUMN IF NOT EXISTS `approval_mode` TEXT AS (JSON_VALUE(doc, '$.approval_mode')) STORED;

-- ---- ro_lines (3 dokumen contoh) ----
CREATE TABLE IF NOT EXISTS `ro_lines` (
  pk VARCHAR(64) NOT NULL PRIMARY KEY COMMENT 'doc.id atau UUID',
  doc LONGTEXT NOT NULL COMMENT 'Dokumen lengkap (JSON)' CHECK (JSON_VALID(doc)),
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  KEY idx_ro_lines_created (created_at, pk)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Koleksi ro_lines (ProcureFlow)';
ALTER TABLE `ro_lines` ADD COLUMN IF NOT EXISTS `id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.id'), 191)) STORED;
ALTER TABLE `ro_lines` ADD INDEX IF NOT EXISTS `idx_ro_lines_id` (`id`);
ALTER TABLE `ro_lines` ADD COLUMN IF NOT EXISTS `base_uom_id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.base_uom_id'), 191)) STORED;
ALTER TABLE `ro_lines` ADD INDEX IF NOT EXISTS `idx_ro_lines_base_uom_id` (`base_uom_id`);
ALTER TABLE `ro_lines` ADD COLUMN IF NOT EXISTS `item_id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.item_id'), 191)) STORED;
ALTER TABLE `ro_lines` ADD INDEX IF NOT EXISTS `idx_ro_lines_item_id` (`item_id`);
ALTER TABLE `ro_lines` ADD COLUMN IF NOT EXISTS `project_id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.project_id'), 191)) STORED;
ALTER TABLE `ro_lines` ADD INDEX IF NOT EXISTS `idx_ro_lines_project_id` (`project_id`);
ALTER TABLE `ro_lines` ADD COLUMN IF NOT EXISTS `ro_id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.ro_id'), 191)) STORED;
ALTER TABLE `ro_lines` ADD INDEX IF NOT EXISTS `idx_ro_lines_ro_id` (`ro_id`);
ALTER TABLE `ro_lines` ADD COLUMN IF NOT EXISTS `unit_id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.unit_id'), 191)) STORED;
ALTER TABLE `ro_lines` ADD INDEX IF NOT EXISTS `idx_ro_lines_unit_id` (`unit_id`);
ALTER TABLE `ro_lines` ADD COLUMN IF NOT EXISTS `uom_id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.uom_id'), 191)) STORED;
ALTER TABLE `ro_lines` ADD INDEX IF NOT EXISTS `idx_ro_lines_uom_id` (`uom_id`);
ALTER TABLE `ro_lines` ADD COLUMN IF NOT EXISTS `warehouse_id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.warehouse_id'), 191)) STORED;
ALTER TABLE `ro_lines` ADD INDEX IF NOT EXISTS `idx_ro_lines_warehouse_id` (`warehouse_id`);
ALTER TABLE `ro_lines` ADD COLUMN IF NOT EXISTS `qty` TEXT AS (JSON_VALUE(doc, '$.qty')) STORED;
ALTER TABLE `ro_lines` ADD COLUMN IF NOT EXISTS `unit` TEXT AS (JSON_VALUE(doc, '$.unit')) STORED;
ALTER TABLE `ro_lines` ADD COLUMN IF NOT EXISTS `notes` TEXT AS (JSON_VALUE(doc, '$.notes')) STORED;
ALTER TABLE `ro_lines` ADD COLUMN IF NOT EXISTS `base_qty` TEXT AS (JSON_VALUE(doc, '$.base_qty')) STORED;
ALTER TABLE `ro_lines` ADD COLUMN IF NOT EXISTS `base_unit` TEXT AS (JSON_VALUE(doc, '$.base_unit')) STORED;
ALTER TABLE `ro_lines` ADD COLUMN IF NOT EXISTS `conversion_factor` TEXT AS (JSON_VALUE(doc, '$.conversion_factor')) STORED;
ALTER TABLE `ro_lines` ADD COLUMN IF NOT EXISTS `display_qty` TEXT AS (JSON_VALUE(doc, '$.display_qty')) STORED;
ALTER TABLE `ro_lines` ADD COLUMN IF NOT EXISTS `display_unit` TEXT AS (JSON_VALUE(doc, '$.display_unit')) STORED;

-- ---- settings (9 dokumen contoh) ----
CREATE TABLE IF NOT EXISTS `settings` (
  pk VARCHAR(64) NOT NULL PRIMARY KEY COMMENT 'doc.id atau UUID',
  doc LONGTEXT NOT NULL COMMENT 'Dokumen lengkap (JSON)' CHECK (JSON_VALID(doc)),
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  KEY idx_settings_created (created_at, pk)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Koleksi settings (ProcureFlow)';
ALTER TABLE `settings` ADD COLUMN IF NOT EXISTS `id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.id'), 191)) STORED;
ALTER TABLE `settings` ADD INDEX IF NOT EXISTS `idx_settings_id` (`id`);
ALTER TABLE `settings` ADD COLUMN IF NOT EXISTS `logo_content_type` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.logo_content_type'), 191)) STORED;
ALTER TABLE `settings` ADD INDEX IF NOT EXISTS `idx_settings_logo_content_type` (`logo_content_type`);
ALTER TABLE `settings` ADD COLUMN IF NOT EXISTS `name` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.name'), 191)) STORED;
ALTER TABLE `settings` ADD INDEX IF NOT EXISTS `idx_settings_name` (`name`);
ALTER TABLE `settings` ADD COLUMN IF NOT EXISTS `po_signature_content_type` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.po_signature_content_type'), 191)) STORED;
ALTER TABLE `settings` ADD INDEX IF NOT EXISTS `idx_settings_po_signature_content_type` (`po_signature_content_type`);
ALTER TABLE `settings` ADD COLUMN IF NOT EXISTS `updated_by` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.updated_by'), 191)) STORED;
ALTER TABLE `settings` ADD INDEX IF NOT EXISTS `idx_settings_updated_by` (`updated_by`);
ALTER TABLE `settings` ADD COLUMN IF NOT EXISTS `username` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.username'), 191)) STORED;
ALTER TABLE `settings` ADD INDEX IF NOT EXISTS `idx_settings_username` (`username`);
ALTER TABLE `settings` ADD COLUMN IF NOT EXISTS `address` TEXT AS (JSON_VALUE(doc, '$.address')) STORED;
ALTER TABLE `settings` ADD COLUMN IF NOT EXISTS `logo_url` TEXT AS (JSON_VALUE(doc, '$.logo_url')) STORED;
ALTER TABLE `settings` ADD COLUMN IF NOT EXISTS `damaged_method` TEXT AS (JSON_VALUE(doc, '$.damaged_method')) STORED;
ALTER TABLE `settings` ADD COLUMN IF NOT EXISTS `app_subtitle` TEXT AS (JSON_VALUE(doc, '$.app_subtitle')) STORED;
ALTER TABLE `settings` ADD COLUMN IF NOT EXISTS `logo_filename` TEXT AS (JSON_VALUE(doc, '$.logo_filename')) STORED;
ALTER TABLE `settings` ADD COLUMN IF NOT EXISTS `logo_path` TEXT AS (JSON_VALUE(doc, '$.logo_path')) STORED;
ALTER TABLE `settings` ADD COLUMN IF NOT EXISTS `logo_size` TEXT AS (JSON_VALUE(doc, '$.logo_size')) STORED;
ALTER TABLE `settings` ADD COLUMN IF NOT EXISTS `logo_version` TEXT AS (JSON_VALUE(doc, '$.logo_version')) STORED;
ALTER TABLE `settings` ADD COLUMN IF NOT EXISTS `po_signature_path` TEXT AS (JSON_VALUE(doc, '$.po_signature_path')) STORED;
ALTER TABLE `settings` ADD COLUMN IF NOT EXISTS `po_signature_version` TEXT AS (JSON_VALUE(doc, '$.po_signature_version')) STORED;
ALTER TABLE `settings` ADD COLUMN IF NOT EXISTS `enabled` TEXT AS (JSON_VALUE(doc, '$.enabled')) STORED;
ALTER TABLE `settings` ADD COLUMN IF NOT EXISTS `from_email` TEXT AS (JSON_VALUE(doc, '$.from_email')) STORED;
ALTER TABLE `settings` ADD COLUMN IF NOT EXISTS `from_name` TEXT AS (JSON_VALUE(doc, '$.from_name')) STORED;
ALTER TABLE `settings` ADD COLUMN IF NOT EXISTS `host` TEXT AS (JSON_VALUE(doc, '$.host')) STORED;
ALTER TABLE `settings` ADD COLUMN IF NOT EXISTS `password` TEXT AS (JSON_VALUE(doc, '$.password')) STORED;
ALTER TABLE `settings` ADD COLUMN IF NOT EXISTS `port` TEXT AS (JSON_VALUE(doc, '$.port')) STORED;
ALTER TABLE `settings` ADD COLUMN IF NOT EXISTS `provider` TEXT AS (JSON_VALUE(doc, '$.provider')) STORED;
ALTER TABLE `settings` ADD COLUMN IF NOT EXISTS `security` TEXT AS (JSON_VALUE(doc, '$.security')) STORED;

-- ---- stock_ledger (357 dokumen contoh) ----
CREATE TABLE IF NOT EXISTS `stock_ledger` (
  pk VARCHAR(64) NOT NULL PRIMARY KEY COMMENT 'doc.id atau UUID',
  doc LONGTEXT NOT NULL COMMENT 'Dokumen lengkap (JSON)' CHECK (JSON_VALID(doc)),
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  KEY idx_stock_ledger_created (created_at, pk)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Koleksi stock_ledger (ProcureFlow)';
ALTER TABLE `stock_ledger` ADD COLUMN IF NOT EXISTS `id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.id'), 191)) STORED;
ALTER TABLE `stock_ledger` ADD INDEX IF NOT EXISTS `idx_stock_ledger_id` (`id`);
ALTER TABLE `stock_ledger` ADD COLUMN IF NOT EXISTS `at` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.at'), 191)) STORED;
ALTER TABLE `stock_ledger` ADD INDEX IF NOT EXISTS `idx_stock_ledger_at` (`at`);
ALTER TABLE `stock_ledger` ADD COLUMN IF NOT EXISTS `division_id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.division_id'), 191)) STORED;
ALTER TABLE `stock_ledger` ADD INDEX IF NOT EXISTS `idx_stock_ledger_division_id` (`division_id`);
ALTER TABLE `stock_ledger` ADD COLUMN IF NOT EXISTS `doc_id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.doc_id'), 191)) STORED;
ALTER TABLE `stock_ledger` ADD INDEX IF NOT EXISTS `idx_stock_ledger_doc_id` (`doc_id`);
ALTER TABLE `stock_ledger` ADD COLUMN IF NOT EXISTS `doc_no` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.doc_no'), 191)) STORED;
ALTER TABLE `stock_ledger` ADD INDEX IF NOT EXISTS `idx_stock_ledger_doc_no` (`doc_no`);
ALTER TABLE `stock_ledger` ADD COLUMN IF NOT EXISTS `doc_type` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.doc_type'), 191)) STORED;
ALTER TABLE `stock_ledger` ADD INDEX IF NOT EXISTS `idx_stock_ledger_doc_type` (`doc_type`);
ALTER TABLE `stock_ledger` ADD COLUMN IF NOT EXISTS `is_reversal` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.is_reversal'), 191)) STORED;
ALTER TABLE `stock_ledger` ADD INDEX IF NOT EXISTS `idx_stock_ledger_is_reversal` (`is_reversal`);
ALTER TABLE `stock_ledger` ADD COLUMN IF NOT EXISTS `item_id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.item_id'), 191)) STORED;
ALTER TABLE `stock_ledger` ADD INDEX IF NOT EXISTS `idx_stock_ledger_item_id` (`item_id`);
ALTER TABLE `stock_ledger` ADD COLUMN IF NOT EXISTS `project_id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.project_id'), 191)) STORED;
ALTER TABLE `stock_ledger` ADD INDEX IF NOT EXISTS `idx_stock_ledger_project_id` (`project_id`);
ALTER TABLE `stock_ledger` ADD COLUMN IF NOT EXISTS `reversal_of_ledger_id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.reversal_of_ledger_id'), 191)) STORED;
ALTER TABLE `stock_ledger` ADD INDEX IF NOT EXISTS `idx_stock_ledger_reversal_of_ledger_id` (`reversal_of_ledger_id`);
ALTER TABLE `stock_ledger` ADD COLUMN IF NOT EXISTS `reversed_at` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.reversed_at'), 191)) STORED;
ALTER TABLE `stock_ledger` ADD INDEX IF NOT EXISTS `idx_stock_ledger_reversed_at` (`reversed_at`);
ALTER TABLE `stock_ledger` ADD COLUMN IF NOT EXISTS `unit_id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.unit_id'), 191)) STORED;
ALTER TABLE `stock_ledger` ADD INDEX IF NOT EXISTS `idx_stock_ledger_unit_id` (`unit_id`);
ALTER TABLE `stock_ledger` ADD COLUMN IF NOT EXISTS `uom_id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.uom_id'), 191)) STORED;
ALTER TABLE `stock_ledger` ADD INDEX IF NOT EXISTS `idx_stock_ledger_uom_id` (`uom_id`);
ALTER TABLE `stock_ledger` ADD COLUMN IF NOT EXISTS `warehouse_id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.warehouse_id'), 191)) STORED;
ALTER TABLE `stock_ledger` ADD INDEX IF NOT EXISTS `idx_stock_ledger_warehouse_id` (`warehouse_id`);
ALTER TABLE `stock_ledger` ADD COLUMN IF NOT EXISTS `qty_in` TEXT AS (JSON_VALUE(doc, '$.qty_in')) STORED;
ALTER TABLE `stock_ledger` ADD COLUMN IF NOT EXISTS `qty_out` TEXT AS (JSON_VALUE(doc, '$.qty_out')) STORED;
ALTER TABLE `stock_ledger` ADD COLUMN IF NOT EXISTS `running_balance` TEXT AS (JSON_VALUE(doc, '$.running_balance')) STORED;
ALTER TABLE `stock_ledger` ADD COLUMN IF NOT EXISTS `user` TEXT AS (JSON_VALUE(doc, '$.user')) STORED;
ALTER TABLE `stock_ledger` ADD COLUMN IF NOT EXISTS `reversed` TEXT AS (JSON_VALUE(doc, '$.reversed')) STORED;
ALTER TABLE `stock_ledger` ADD COLUMN IF NOT EXISTS `reversal_reason` TEXT AS (JSON_VALUE(doc, '$.reversal_reason')) STORED;
ALTER TABLE `stock_ledger` ADD COLUMN IF NOT EXISTS `display_unit` TEXT AS (JSON_VALUE(doc, '$.display_unit')) STORED;
ALTER TABLE `stock_ledger` ADD COLUMN IF NOT EXISTS `conversion_factor` TEXT AS (JSON_VALUE(doc, '$.conversion_factor')) STORED;
ALTER TABLE `stock_ledger` ADD COLUMN IF NOT EXISTS `unit_cost` TEXT AS (JSON_VALUE(doc, '$.unit_cost')) STORED;
ALTER TABLE `stock_ledger` ADD COLUMN IF NOT EXISTS `purchase_price` TEXT AS (JSON_VALUE(doc, '$.purchase_price')) STORED;
ALTER TABLE `stock_ledger` ADD COLUMN IF NOT EXISTS `value_adjustment` TEXT AS (JSON_VALUE(doc, '$.value_adjustment')) STORED;
ALTER TABLE `stock_ledger` ADD COLUMN IF NOT EXISTS `opening_balance` TEXT AS (JSON_VALUE(doc, '$.opening_balance')) STORED;

-- ---- supplier_categories (21 dokumen contoh) ----
CREATE TABLE IF NOT EXISTS `supplier_categories` (
  pk VARCHAR(64) NOT NULL PRIMARY KEY COMMENT 'doc.id atau UUID',
  doc LONGTEXT NOT NULL COMMENT 'Dokumen lengkap (JSON)' CHECK (JSON_VALID(doc)),
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  KEY idx_supplier_categories_created (created_at, pk)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Koleksi supplier_categories (ProcureFlow)';
ALTER TABLE `supplier_categories` ADD COLUMN IF NOT EXISTS `id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.id'), 191)) STORED;
ALTER TABLE `supplier_categories` ADD INDEX IF NOT EXISTS `idx_supplier_categories_id` (`id`);
ALTER TABLE `supplier_categories` ADD COLUMN IF NOT EXISTS `code` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.code'), 191)) STORED;
ALTER TABLE `supplier_categories` ADD INDEX IF NOT EXISTS `idx_supplier_categories_code` (`code`);
ALTER TABLE `supplier_categories` ADD COLUMN IF NOT EXISTS `is_active` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.is_active'), 191)) STORED;
ALTER TABLE `supplier_categories` ADD INDEX IF NOT EXISTS `idx_supplier_categories_is_active` (`is_active`);
ALTER TABLE `supplier_categories` ADD COLUMN IF NOT EXISTS `name` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.name'), 191)) STORED;
ALTER TABLE `supplier_categories` ADD INDEX IF NOT EXISTS `idx_supplier_categories_name` (`name`);

-- ---- suppliers (63 dokumen contoh) ----
CREATE TABLE IF NOT EXISTS `suppliers` (
  pk VARCHAR(64) NOT NULL PRIMARY KEY COMMENT 'doc.id atau UUID',
  doc LONGTEXT NOT NULL COMMENT 'Dokumen lengkap (JSON)' CHECK (JSON_VALID(doc)),
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  KEY idx_suppliers_created (created_at, pk)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Koleksi suppliers (ProcureFlow)';
ALTER TABLE `suppliers` ADD COLUMN IF NOT EXISTS `id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.id'), 191)) STORED;
ALTER TABLE `suppliers` ADD INDEX IF NOT EXISTS `idx_suppliers_id` (`id`);
ALTER TABLE `suppliers` ADD COLUMN IF NOT EXISTS `code` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.code'), 191)) STORED;
ALTER TABLE `suppliers` ADD INDEX IF NOT EXISTS `idx_suppliers_code` (`code`);
ALTER TABLE `suppliers` ADD COLUMN IF NOT EXISTS `default_tax_id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.default_tax_id'), 191)) STORED;
ALTER TABLE `suppliers` ADD INDEX IF NOT EXISTS `idx_suppliers_default_tax_id` (`default_tax_id`);
ALTER TABLE `suppliers` ADD COLUMN IF NOT EXISTS `email` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.email'), 191)) STORED;
ALTER TABLE `suppliers` ADD INDEX IF NOT EXISTS `idx_suppliers_email` (`email`);
ALTER TABLE `suppliers` ADD COLUMN IF NOT EXISTS `is_active` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.is_active'), 191)) STORED;
ALTER TABLE `suppliers` ADD INDEX IF NOT EXISTS `idx_suppliers_is_active` (`is_active`);
ALTER TABLE `suppliers` ADD COLUMN IF NOT EXISTS `name` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.name'), 191)) STORED;
ALTER TABLE `suppliers` ADD INDEX IF NOT EXISTS `idx_suppliers_name` (`name`);
ALTER TABLE `suppliers` ADD COLUMN IF NOT EXISTS `supplier_category_id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.supplier_category_id'), 191)) STORED;
ALTER TABLE `suppliers` ADD INDEX IF NOT EXISTS `idx_suppliers_supplier_category_id` (`supplier_category_id`);
ALTER TABLE `suppliers` ADD COLUMN IF NOT EXISTS `supplier_type` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.supplier_type'), 191)) STORED;
ALTER TABLE `suppliers` ADD INDEX IF NOT EXISTS `idx_suppliers_supplier_type` (`supplier_type`);
ALTER TABLE `suppliers` ADD COLUMN IF NOT EXISTS `address` TEXT AS (JSON_VALUE(doc, '$.address')) STORED;
ALTER TABLE `suppliers` ADD COLUMN IF NOT EXISTS `city` TEXT AS (JSON_VALUE(doc, '$.city')) STORED;
ALTER TABLE `suppliers` ADD COLUMN IF NOT EXISTS `contact` TEXT AS (JSON_VALUE(doc, '$.contact')) STORED;
ALTER TABLE `suppliers` ADD COLUMN IF NOT EXISTS `country` TEXT AS (JSON_VALUE(doc, '$.country')) STORED;
ALTER TABLE `suppliers` ADD COLUMN IF NOT EXISTS `currency` TEXT AS (JSON_VALUE(doc, '$.currency')) STORED;
ALTER TABLE `suppliers` ADD COLUMN IF NOT EXISTS `default_tax_name` TEXT AS (JSON_VALUE(doc, '$.default_tax_name')) STORED;
ALTER TABLE `suppliers` ADD COLUMN IF NOT EXISTS `default_tax_rate` TEXT AS (JSON_VALUE(doc, '$.default_tax_rate')) STORED;
ALTER TABLE `suppliers` ADD COLUMN IF NOT EXISTS `lead_time_days` TEXT AS (JSON_VALUE(doc, '$.lead_time_days')) STORED;
ALTER TABLE `suppliers` ADD COLUMN IF NOT EXISTS `legal_name` TEXT AS (JSON_VALUE(doc, '$.legal_name')) STORED;
ALTER TABLE `suppliers` ADD COLUMN IF NOT EXISTS `min_order` TEXT AS (JSON_VALUE(doc, '$.min_order')) STORED;
ALTER TABLE `suppliers` ADD COLUMN IF NOT EXISTS `payment_term` TEXT AS (JSON_VALUE(doc, '$.payment_term')) STORED;
ALTER TABLE `suppliers` ADD COLUMN IF NOT EXISTS `phone` TEXT AS (JSON_VALUE(doc, '$.phone')) STORED;
ALTER TABLE `suppliers` ADD COLUMN IF NOT EXISTS `pkp` TEXT AS (JSON_VALUE(doc, '$.pkp')) STORED;
ALTER TABLE `suppliers` ADD COLUMN IF NOT EXISTS `postal_code` TEXT AS (JSON_VALUE(doc, '$.postal_code')) STORED;
ALTER TABLE `suppliers` ADD COLUMN IF NOT EXISTS `province` TEXT AS (JSON_VALUE(doc, '$.province')) STORED;
ALTER TABLE `suppliers` ADD COLUMN IF NOT EXISTS `supplier_category_name` TEXT AS (JSON_VALUE(doc, '$.supplier_category_name')) STORED;
ALTER TABLE `suppliers` ADD COLUMN IF NOT EXISTS `npwp` TEXT AS (JSON_VALUE(doc, '$.npwp')) STORED;
ALTER TABLE `suppliers` ADD COLUMN IF NOT EXISTS `nib` TEXT AS (JSON_VALUE(doc, '$.nib')) STORED;
ALTER TABLE `suppliers` ADD COLUMN IF NOT EXISTS `delivery_days` TEXT AS (JSON_VALUE(doc, '$.delivery_days')) STORED;
ALTER TABLE `suppliers` ADD COLUMN IF NOT EXISTS `service_area` TEXT AS (JSON_VALUE(doc, '$.service_area')) STORED;

-- ---- taxes (1 dokumen contoh) ----
CREATE TABLE IF NOT EXISTS `taxes` (
  pk VARCHAR(64) NOT NULL PRIMARY KEY COMMENT 'doc.id atau UUID',
  doc LONGTEXT NOT NULL COMMENT 'Dokumen lengkap (JSON)' CHECK (JSON_VALID(doc)),
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  KEY idx_taxes_created (created_at, pk)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Koleksi taxes (ProcureFlow)';
ALTER TABLE `taxes` ADD COLUMN IF NOT EXISTS `id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.id'), 191)) STORED;
ALTER TABLE `taxes` ADD INDEX IF NOT EXISTS `idx_taxes_id` (`id`);
ALTER TABLE `taxes` ADD COLUMN IF NOT EXISTS `code` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.code'), 191)) STORED;
ALTER TABLE `taxes` ADD INDEX IF NOT EXISTS `idx_taxes_code` (`code`);
ALTER TABLE `taxes` ADD COLUMN IF NOT EXISTS `is_active` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.is_active'), 191)) STORED;
ALTER TABLE `taxes` ADD INDEX IF NOT EXISTS `idx_taxes_is_active` (`is_active`);
ALTER TABLE `taxes` ADD COLUMN IF NOT EXISTS `name` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.name'), 191)) STORED;
ALTER TABLE `taxes` ADD INDEX IF NOT EXISTS `idx_taxes_name` (`name`);
ALTER TABLE `taxes` ADD COLUMN IF NOT EXISTS `rate` TEXT AS (JSON_VALUE(doc, '$.rate')) STORED;

-- ---- transfer_lines (0 dokumen contoh) ----
CREATE TABLE IF NOT EXISTS `transfer_lines` (
  pk VARCHAR(64) NOT NULL PRIMARY KEY COMMENT 'doc.id atau UUID',
  doc LONGTEXT NOT NULL COMMENT 'Dokumen lengkap (JSON)' CHECK (JSON_VALID(doc)),
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  KEY idx_transfer_lines_created (created_at, pk)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Koleksi transfer_lines (ProcureFlow)';
ALTER TABLE `transfer_lines` ADD COLUMN IF NOT EXISTS `id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.id'), 191)) STORED;
ALTER TABLE `transfer_lines` ADD INDEX IF NOT EXISTS `idx_transfer_lines_id` (`id`);
ALTER TABLE `transfer_lines` ADD COLUMN IF NOT EXISTS `code` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.code'), 191)) STORED;
ALTER TABLE `transfer_lines` ADD INDEX IF NOT EXISTS `idx_transfer_lines_code` (`code`);
ALTER TABLE `transfer_lines` ADD COLUMN IF NOT EXISTS `no` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.no'), 191)) STORED;
ALTER TABLE `transfer_lines` ADD INDEX IF NOT EXISTS `idx_transfer_lines_no` (`no`);
ALTER TABLE `transfer_lines` ADD COLUMN IF NOT EXISTS `status` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.status'), 191)) STORED;
ALTER TABLE `transfer_lines` ADD INDEX IF NOT EXISTS `idx_transfer_lines_status` (`status`);

-- ---- transfers (0 dokumen contoh) ----
CREATE TABLE IF NOT EXISTS `transfers` (
  pk VARCHAR(64) NOT NULL PRIMARY KEY COMMENT 'doc.id atau UUID',
  doc LONGTEXT NOT NULL COMMENT 'Dokumen lengkap (JSON)' CHECK (JSON_VALID(doc)),
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  KEY idx_transfers_created (created_at, pk)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Koleksi transfers (ProcureFlow)';
ALTER TABLE `transfers` ADD COLUMN IF NOT EXISTS `id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.id'), 191)) STORED;
ALTER TABLE `transfers` ADD INDEX IF NOT EXISTS `idx_transfers_id` (`id`);
ALTER TABLE `transfers` ADD COLUMN IF NOT EXISTS `code` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.code'), 191)) STORED;
ALTER TABLE `transfers` ADD INDEX IF NOT EXISTS `idx_transfers_code` (`code`);
ALTER TABLE `transfers` ADD COLUMN IF NOT EXISTS `no` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.no'), 191)) STORED;
ALTER TABLE `transfers` ADD INDEX IF NOT EXISTS `idx_transfers_no` (`no`);
ALTER TABLE `transfers` ADD COLUMN IF NOT EXISTS `status` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.status'), 191)) STORED;
ALTER TABLE `transfers` ADD INDEX IF NOT EXISTS `idx_transfers_status` (`status`);

-- ---- units (88 dokumen contoh) ----
CREATE TABLE IF NOT EXISTS `units` (
  pk VARCHAR(64) NOT NULL PRIMARY KEY COMMENT 'doc.id atau UUID',
  doc LONGTEXT NOT NULL COMMENT 'Dokumen lengkap (JSON)' CHECK (JSON_VALID(doc)),
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  KEY idx_units_created (created_at, pk)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Koleksi units (ProcureFlow)';
ALTER TABLE `units` ADD COLUMN IF NOT EXISTS `id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.id'), 191)) STORED;
ALTER TABLE `units` ADD INDEX IF NOT EXISTS `idx_units_id` (`id`);
ALTER TABLE `units` ADD COLUMN IF NOT EXISTS `asset_no` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.asset_no'), 191)) STORED;
ALTER TABLE `units` ADD INDEX IF NOT EXISTS `idx_units_asset_no` (`asset_no`);
ALTER TABLE `units` ADD COLUMN IF NOT EXISTS `code` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.code'), 191)) STORED;
ALTER TABLE `units` ADD INDEX IF NOT EXISTS `idx_units_code` (`code`);
ALTER TABLE `units` ADD COLUMN IF NOT EXISTS `division_id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.division_id'), 191)) STORED;
ALTER TABLE `units` ADD INDEX IF NOT EXISTS `idx_units_division_id` (`division_id`);
ALTER TABLE `units` ADD COLUMN IF NOT EXISTS `is_active` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.is_active'), 191)) STORED;
ALTER TABLE `units` ADD INDEX IF NOT EXISTS `idx_units_is_active` (`is_active`);
ALTER TABLE `units` ADD COLUMN IF NOT EXISTS `name` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.name'), 191)) STORED;
ALTER TABLE `units` ADD INDEX IF NOT EXISTS `idx_units_name` (`name`);
ALTER TABLE `units` ADD COLUMN IF NOT EXISTS `plate_no` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.plate_no'), 191)) STORED;
ALTER TABLE `units` ADD INDEX IF NOT EXISTS `idx_units_plate_no` (`plate_no`);
ALTER TABLE `units` ADD COLUMN IF NOT EXISTS `type` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.type'), 191)) STORED;
ALTER TABLE `units` ADD INDEX IF NOT EXISTS `idx_units_type` (`type`);
ALTER TABLE `units` ADD COLUMN IF NOT EXISTS `year` TEXT AS (JSON_VALUE(doc, '$.year')) STORED;
ALTER TABLE `units` ADD COLUMN IF NOT EXISTS `brand` TEXT AS (JSON_VALUE(doc, '$.brand')) STORED;
ALTER TABLE `units` ADD COLUMN IF NOT EXISTS `model` TEXT AS (JSON_VALUE(doc, '$.model')) STORED;

-- ---- uoms (27 dokumen contoh) ----
CREATE TABLE IF NOT EXISTS `uoms` (
  pk VARCHAR(64) NOT NULL PRIMARY KEY COMMENT 'doc.id atau UUID',
  doc LONGTEXT NOT NULL COMMENT 'Dokumen lengkap (JSON)' CHECK (JSON_VALID(doc)),
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  KEY idx_uoms_created (created_at, pk)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Koleksi uoms (ProcureFlow)';
ALTER TABLE `uoms` ADD COLUMN IF NOT EXISTS `id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.id'), 191)) STORED;
ALTER TABLE `uoms` ADD INDEX IF NOT EXISTS `idx_uoms_id` (`id`);
ALTER TABLE `uoms` ADD COLUMN IF NOT EXISTS `code` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.code'), 191)) STORED;
ALTER TABLE `uoms` ADD INDEX IF NOT EXISTS `idx_uoms_code` (`code`);
ALTER TABLE `uoms` ADD COLUMN IF NOT EXISTS `is_active` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.is_active'), 191)) STORED;
ALTER TABLE `uoms` ADD INDEX IF NOT EXISTS `idx_uoms_is_active` (`is_active`);
ALTER TABLE `uoms` ADD COLUMN IF NOT EXISTS `name` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.name'), 191)) STORED;
ALTER TABLE `uoms` ADD INDEX IF NOT EXISTS `idx_uoms_name` (`name`);
ALTER TABLE `uoms` ADD COLUMN IF NOT EXISTS `symbol` TEXT AS (JSON_VALUE(doc, '$.symbol')) STORED;

-- ---- users (1 dokumen contoh) ----
CREATE TABLE IF NOT EXISTS `users` (
  pk VARCHAR(64) NOT NULL PRIMARY KEY COMMENT 'doc.id atau UUID',
  doc LONGTEXT NOT NULL COMMENT 'Dokumen lengkap (JSON)' CHECK (JSON_VALID(doc)),
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  KEY idx_users_created (created_at, pk)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Koleksi users (ProcureFlow)';
ALTER TABLE `users` ADD COLUMN IF NOT EXISTS `id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.id'), 191)) STORED;
ALTER TABLE `users` ADD INDEX IF NOT EXISTS `idx_users_id` (`id`);
ALTER TABLE `users` ADD COLUMN IF NOT EXISTS `email` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.email'), 191)) STORED;
ALTER TABLE `users` ADD INDEX IF NOT EXISTS `idx_users_email` (`email`);
ALTER TABLE `users` ADD COLUMN IF NOT EXISTS `is_active` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.is_active'), 191)) STORED;
ALTER TABLE `users` ADD INDEX IF NOT EXISTS `idx_users_is_active` (`is_active`);
ALTER TABLE `users` ADD COLUMN IF NOT EXISTS `name` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.name'), 191)) STORED;
ALTER TABLE `users` ADD INDEX IF NOT EXISTS `idx_users_name` (`name`);
ALTER TABLE `users` ADD COLUMN IF NOT EXISTS `role` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.role'), 191)) STORED;
ALTER TABLE `users` ADD INDEX IF NOT EXISTS `idx_users_role` (`role`);
ALTER TABLE `users` ADD COLUMN IF NOT EXISTS `scope` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.scope'), 191)) STORED;
ALTER TABLE `users` ADD INDEX IF NOT EXISTS `idx_users_scope` (`scope`);
ALTER TABLE `users` ADD COLUMN IF NOT EXISTS `password_hash` TEXT AS (JSON_VALUE(doc, '$.password_hash')) STORED;
ALTER TABLE `users` ADD COLUMN IF NOT EXISTS `token_version` TEXT AS (JSON_VALUE(doc, '$.token_version')) STORED;
ALTER TABLE `users` ADD COLUMN IF NOT EXISTS `signature_url` TEXT AS (JSON_VALUE(doc, '$.signature_url')) STORED;

-- ---- verifications (37 dokumen contoh) ----
CREATE TABLE IF NOT EXISTS `verifications` (
  pk VARCHAR(64) NOT NULL PRIMARY KEY COMMENT 'doc.id atau UUID',
  doc LONGTEXT NOT NULL COMMENT 'Dokumen lengkap (JSON)' CHECK (JSON_VALID(doc)),
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  KEY idx_verifications_created (created_at, pk)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Koleksi verifications (ProcureFlow)';
ALTER TABLE `verifications` ADD COLUMN IF NOT EXISTS `id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.id'), 191)) STORED;
ALTER TABLE `verifications` ADD INDEX IF NOT EXISTS `idx_verifications_id` (`id`);
ALTER TABLE `verifications` ADD COLUMN IF NOT EXISTS `code` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.code'), 191)) STORED;
ALTER TABLE `verifications` ADD INDEX IF NOT EXISTS `idx_verifications_code` (`code`);
ALTER TABLE `verifications` ADD COLUMN IF NOT EXISTS `created_by` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.created_by'), 191)) STORED;
ALTER TABLE `verifications` ADD INDEX IF NOT EXISTS `idx_verifications_created_by` (`created_by`);
ALTER TABLE `verifications` ADD COLUMN IF NOT EXISTS `doc_id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.doc_id'), 191)) STORED;
ALTER TABLE `verifications` ADD INDEX IF NOT EXISTS `idx_verifications_doc_id` (`doc_id`);
ALTER TABLE `verifications` ADD COLUMN IF NOT EXISTS `doc_no` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.doc_no'), 191)) STORED;
ALTER TABLE `verifications` ADD INDEX IF NOT EXISTS `idx_verifications_doc_no` (`doc_no`);
ALTER TABLE `verifications` ADD COLUMN IF NOT EXISTS `doc_type` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.doc_type'), 191)) STORED;
ALTER TABLE `verifications` ADD INDEX IF NOT EXISTS `idx_verifications_doc_type` (`doc_type`);
ALTER TABLE `verifications` ADD COLUMN IF NOT EXISTS `status` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.status'), 191)) STORED;
ALTER TABLE `verifications` ADD INDEX IF NOT EXISTS `idx_verifications_status` (`status`);

-- ---- warehouses (4 dokumen contoh) ----
CREATE TABLE IF NOT EXISTS `warehouses` (
  pk VARCHAR(64) NOT NULL PRIMARY KEY COMMENT 'doc.id atau UUID',
  doc LONGTEXT NOT NULL COMMENT 'Dokumen lengkap (JSON)' CHECK (JSON_VALID(doc)),
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  KEY idx_warehouses_created (created_at, pk)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Koleksi warehouses (ProcureFlow)';
ALTER TABLE `warehouses` ADD COLUMN IF NOT EXISTS `id` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.id'), 191)) STORED;
ALTER TABLE `warehouses` ADD INDEX IF NOT EXISTS `idx_warehouses_id` (`id`);
ALTER TABLE `warehouses` ADD COLUMN IF NOT EXISTS `code` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.code'), 191)) STORED;
ALTER TABLE `warehouses` ADD INDEX IF NOT EXISTS `idx_warehouses_code` (`code`);
ALTER TABLE `warehouses` ADD COLUMN IF NOT EXISTS `is_active` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.is_active'), 191)) STORED;
ALTER TABLE `warehouses` ADD INDEX IF NOT EXISTS `idx_warehouses_is_active` (`is_active`);
ALTER TABLE `warehouses` ADD COLUMN IF NOT EXISTS `name` VARCHAR(191) AS (LEFT(JSON_VALUE(doc, '$.name'), 191)) STORED;
ALTER TABLE `warehouses` ADD INDEX IF NOT EXISTS `idx_warehouses_name` (`name`);

-- ---- Ringkasan jumlah data per tabel (untuk phpMyAdmin) ----
CREATE OR REPLACE VIEW v_ringkasan_data AS
SELECT 'adjustment_lines' AS tabel, COUNT(*) AS jumlah, MAX(updated_at) AS terakhir_diubah FROM `adjustment_lines`
UNION ALL
SELECT 'adjustments' AS tabel, COUNT(*) AS jumlah, MAX(updated_at) AS terakhir_diubah FROM `adjustments`
UNION ALL
SELECT 'allocations' AS tabel, COUNT(*) AS jumlah, MAX(updated_at) AS terakhir_diubah FROM `allocations`
UNION ALL
SELECT 'approval_tasks' AS tabel, COUNT(*) AS jumlah, MAX(updated_at) AS terakhir_diubah FROM `approval_tasks`
UNION ALL
SELECT 'attachments' AS tabel, COUNT(*) AS jumlah, MAX(updated_at) AS terakhir_diubah FROM `attachments`
UNION ALL
SELECT 'audit_logs' AS tabel, COUNT(*) AS jumlah, MAX(updated_at) AS terakhir_diubah FROM `audit_logs`
UNION ALL
SELECT 'contacts' AS tabel, COUNT(*) AS jumlah, MAX(updated_at) AS terakhir_diubah FROM `contacts`
UNION ALL
SELECT 'counters' AS tabel, COUNT(*) AS jumlah, MAX(updated_at) AS terakhir_diubah FROM `counters`
UNION ALL
SELECT 'divisions' AS tabel, COUNT(*) AS jumlah, MAX(updated_at) AS terakhir_diubah FROM `divisions`
UNION ALL
SELECT 'do' AS tabel, COUNT(*) AS jumlah, MAX(updated_at) AS terakhir_diubah FROM `do`
UNION ALL
SELECT 'do_lines' AS tabel, COUNT(*) AS jumlah, MAX(updated_at) AS terakhir_diubah FROM `do_lines`
UNION ALL
SELECT 'item_categories' AS tabel, COUNT(*) AS jumlah, MAX(updated_at) AS terakhir_diubah FROM `item_categories`
UNION ALL
SELECT 'item_warehouse' AS tabel, COUNT(*) AS jumlah, MAX(updated_at) AS terakhir_diubah FROM `item_warehouse`
UNION ALL
SELECT 'items' AS tabel, COUNT(*) AS jumlah, MAX(updated_at) AS terakhir_diubah FROM `items`
UNION ALL
SELECT 'loan_lines' AS tabel, COUNT(*) AS jumlah, MAX(updated_at) AS terakhir_diubah FROM `loan_lines`
UNION ALL
SELECT 'loan_return_lines' AS tabel, COUNT(*) AS jumlah, MAX(updated_at) AS terakhir_diubah FROM `loan_return_lines`
UNION ALL
SELECT 'loan_returns' AS tabel, COUNT(*) AS jumlah, MAX(updated_at) AS terakhir_diubah FROM `loan_returns`
UNION ALL
SELECT 'loans' AS tabel, COUNT(*) AS jumlah, MAX(updated_at) AS terakhir_diubah FROM `loans`
UNION ALL
SELECT 'login_attempts' AS tabel, COUNT(*) AS jumlah, MAX(updated_at) AS terakhir_diubah FROM `login_attempts`
UNION ALL
SELECT 'mi' AS tabel, COUNT(*) AS jumlah, MAX(updated_at) AS terakhir_diubah FROM `mi`
UNION ALL
SELECT 'mi_lines' AS tabel, COUNT(*) AS jumlah, MAX(updated_at) AS terakhir_diubah FROM `mi_lines`
UNION ALL
SELECT 'mro' AS tabel, COUNT(*) AS jumlah, MAX(updated_at) AS terakhir_diubah FROM `mro`
UNION ALL
SELECT 'mro_lines' AS tabel, COUNT(*) AS jumlah, MAX(updated_at) AS terakhir_diubah FROM `mro_lines`
UNION ALL
SELECT 'notifications' AS tabel, COUNT(*) AS jumlah, MAX(updated_at) AS terakhir_diubah FROM `notifications`
UNION ALL
SELECT 'opening_inventory' AS tabel, COUNT(*) AS jumlah, MAX(updated_at) AS terakhir_diubah FROM `opening_inventory`
UNION ALL
SELECT 'opname' AS tabel, COUNT(*) AS jumlah, MAX(updated_at) AS terakhir_diubah FROM `opname`
UNION ALL
SELECT 'opname_lines' AS tabel, COUNT(*) AS jumlah, MAX(updated_at) AS terakhir_diubah FROM `opname_lines`
UNION ALL
SELECT 'po' AS tabel, COUNT(*) AS jumlah, MAX(updated_at) AS terakhir_diubah FROM `po`
UNION ALL
SELECT 'po_approvals' AS tabel, COUNT(*) AS jumlah, MAX(updated_at) AS terakhir_diubah FROM `po_approvals`
UNION ALL
SELECT 'po_lines' AS tabel, COUNT(*) AS jumlah, MAX(updated_at) AS terakhir_diubah FROM `po_lines`
UNION ALL
SELECT 'print_templates' AS tabel, COUNT(*) AS jumlah, MAX(updated_at) AS terakhir_diubah FROM `print_templates`
UNION ALL
SELECT 'projects' AS tabel, COUNT(*) AS jumlah, MAX(updated_at) AS terakhir_diubah FROM `projects`
UNION ALL
SELECT 'ro' AS tabel, COUNT(*) AS jumlah, MAX(updated_at) AS terakhir_diubah FROM `ro`
UNION ALL
SELECT 'ro_lines' AS tabel, COUNT(*) AS jumlah, MAX(updated_at) AS terakhir_diubah FROM `ro_lines`
UNION ALL
SELECT 'settings' AS tabel, COUNT(*) AS jumlah, MAX(updated_at) AS terakhir_diubah FROM `settings`
UNION ALL
SELECT 'stock_ledger' AS tabel, COUNT(*) AS jumlah, MAX(updated_at) AS terakhir_diubah FROM `stock_ledger`
UNION ALL
SELECT 'supplier_categories' AS tabel, COUNT(*) AS jumlah, MAX(updated_at) AS terakhir_diubah FROM `supplier_categories`
UNION ALL
SELECT 'suppliers' AS tabel, COUNT(*) AS jumlah, MAX(updated_at) AS terakhir_diubah FROM `suppliers`
UNION ALL
SELECT 'taxes' AS tabel, COUNT(*) AS jumlah, MAX(updated_at) AS terakhir_diubah FROM `taxes`
UNION ALL
SELECT 'transfer_lines' AS tabel, COUNT(*) AS jumlah, MAX(updated_at) AS terakhir_diubah FROM `transfer_lines`
UNION ALL
SELECT 'transfers' AS tabel, COUNT(*) AS jumlah, MAX(updated_at) AS terakhir_diubah FROM `transfers`
UNION ALL
SELECT 'units' AS tabel, COUNT(*) AS jumlah, MAX(updated_at) AS terakhir_diubah FROM `units`
UNION ALL
SELECT 'uoms' AS tabel, COUNT(*) AS jumlah, MAX(updated_at) AS terakhir_diubah FROM `uoms`
UNION ALL
SELECT 'users' AS tabel, COUNT(*) AS jumlah, MAX(updated_at) AS terakhir_diubah FROM `users`
UNION ALL
SELECT 'verifications' AS tabel, COUNT(*) AS jumlah, MAX(updated_at) AS terakhir_diubah FROM `verifications`
UNION ALL
SELECT 'warehouses' AS tabel, COUNT(*) AS jumlah, MAX(updated_at) AS terakhir_diubah FROM `warehouses`;
