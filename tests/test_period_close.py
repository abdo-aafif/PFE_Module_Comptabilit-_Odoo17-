from datetime import date
from odoo.exceptions import UserError, ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install', 'omega_close')
class TestPeriodClose(TransactionCase):
    """Tests de la clôture comptable : contraintes, accès, workflow."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.Close = cls.env['account.period.close']

    def _make_close(self, **overrides):
        vals = {
            'close_type': 'monthly',
            'date_from': date(2025, 1, 1),
            'date_to': date(2025, 1, 31),
            'date_close': date(2025, 2, 1),
        }
        vals.update(overrides)
        return self.Close.create(vals)

    def test_initial_state_is_draft(self):
        rec = self._make_close()
        self.assertEqual(rec.state, 'draft')

    def test_sequence_name_assigned(self):
        rec = self._make_close()
        self.assertNotEqual(rec.name, '/')
        self.assertTrue(rec.name)

    def test_cannot_delete_done_closure(self):
        rec = self._make_close()
        rec.state = 'done'
        with self.assertRaises(UserError):
            rec.unlink()

    def test_can_delete_draft_closure(self):
        rec = self._make_close()
        rec.unlink()  # should not raise

    def test_unique_done_closure_constraint(self):
        rec1 = self._make_close(close_type='monthly')
        rec1.state = 'done'

        rec2 = self._make_close(close_type='monthly')
        with self.assertRaises(ValidationError):
            rec2.state = 'done'

    def test_view_opening_move_requires_one(self):
        rec = self._make_close()
        with self.assertRaises(UserError):
            rec.action_view_opening_move()

    def test_unlock_requires_manager_group(self):
        """Seul un Account Manager peut déverrouiller une clôture."""
        # Créer un utilisateur sans le groupe manager
        user = self.env['res.users'].create({
            'name': 'Comptable test',
            'login': 'comptable_test_unlock',
            'email': 'test_unlock@test.local',
            'groups_id': [(6, 0, [self.env.ref('account.group_account_user').id])],
        })
        rec = self._make_close()
        rec.state = 'done'
        rec.note = 'Motif test'
        with self.assertRaises(UserError):
            rec.with_user(user).action_unlock()

    def test_unlock_requires_state_done(self):
        """On ne peut pas déverrouiller une clôture qui n'est pas en état 'done'."""
        rec = self._make_close()
        # En 'draft' → impossible
        manager = self.env.ref('base.user_admin')
        with self.assertRaises(UserError):
            rec.with_user(manager).action_unlock()

    def test_unlock_requires_reason(self):
        """Un manager qui déverrouille doit fournir un motif (note non vide)."""
        rec = self._make_close()
        rec.state = 'done'
        rec.note = '   '  # vide
        manager = self.env.ref('base.user_admin')
        with self.assertRaises(UserError):
            rec.with_user(manager).action_unlock()
