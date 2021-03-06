import numpy as np
import numpy.testing as npt
import pytest
from openscm_units import unit_registry as ur
from test_model_base import TwoLayerVariantTester

from openscm_twolayermodel import ImpulseResponseModel, TwoLayerModel
from openscm_twolayermodel.base import _calculate_geoffroy_helper_parameters
from openscm_twolayermodel.constants import DENSITY_WATER, HEAT_CAPACITY_WATER


class TestImpulseResponseModel(TwoLayerVariantTester):
    tmodel = ImpulseResponseModel

    parameters = dict(
        q1=0.33 * ur("delta_degC/(W/m^2)"),
        q2=0.41 * ur("delta_degC/(W/m^2)"),
        d1=239.0 * ur("yr"),
        d2=4.1 * ur("yr"),
        efficacy=1.0 * ur("dimensionless"),
        delta_t=1 * ur("yr"),
    )

    def test_init(self):
        init_kwargs = dict(
            q1=0.3 * ur("delta_degC/(W/m^2)"),
            q2=0.4 * ur("delta_degC/(W/m^2)"),
            d1=25.0 * ur("yr"),
            d2=300 * ur("yr"),
            efficacy=1.1 * ur("dimensionless"),
            delta_t=1 / 12 * ur("yr"),
        )

        res = self.tmodel(**init_kwargs)

        for k, v in init_kwargs.items():
            assert getattr(res, k) == v, "{} not set properly".format(k)

        assert np.isnan(res.erf)
        assert np.isnan(res._temp1_mag)
        assert np.isnan(res._temp2_mag)
        assert np.isnan(res._rndt_mag)

    def test_init_backwards_timescales_error(self):
        init_kwargs = dict(d1=250.0 * ur("yr"), d2=3 * ur("yr"),)

        error_msg = "The short-timescale must be d1"
        with pytest.raises(ValueError, match=error_msg):
            self.tmodel(**init_kwargs)

    def test_calculate_next_temp(self, check_same_unit):
        tdelta_t = 30 * 24 * 60 * 60
        ttemp = 0.1
        tq = 0.4
        td = 35.0
        tf = 1.2

        res = self.tmodel._calculate_next_temp(tdelta_t, ttemp, tq, td, tf)

        expected = ttemp * np.exp(-tdelta_t / td) + tf * tq * (
            1 - np.exp(-tdelta_t / td)
        )

        npt.assert_equal(res, expected)

        check_same_unit(self.tmodel._temp1_unit, self.tmodel._temp2_unit)
        check_same_unit(self.tmodel._q1_unit, self.tmodel._q2_unit)
        check_same_unit(self.tmodel._delta_t_unit, self.tmodel._d1_unit)
        check_same_unit(self.tmodel._delta_t_unit, self.tmodel._d2_unit)
        check_same_unit(
            self.tmodel._temp1_unit,
            (1.0 * ur(self.tmodel._erf_unit) * 1.0 * ur(self.tmodel._q1_unit)).units,
        )

    def test_calculate_next_rndt(self, check_same_unit):
        ttemp1 = 1.1
        ttemp_2 = 0.6
        tq1 = 0.5
        tq2 = 0.3
        td1 = 30
        td2 = 600
        terf = 1.2
        tefficacy = 1.13

        helper = self.tmodel(
            q1=tq1 * ur("delta_degC/(W/m^2)"),
            q2=tq2 * ur("delta_degC/(W/m^2)"),
            d1=td1 * ur("yr"),
            d2=td2 * ur("yr"),
            efficacy=tefficacy * ur("dimensionless"),
        )
        helper_twolayer = TwoLayerModel(**helper.get_two_layer_parameters())

        gh = _calculate_geoffroy_helper_parameters(
            helper_twolayer.du,
            helper_twolayer.dl,
            helper_twolayer.lambda0,
            helper_twolayer.efficacy,
            helper_twolayer.eta,
        )
        # see notebook for discussion of why this is so
        efficacy_term = (
            helper_twolayer.eta
            * (helper_twolayer.efficacy - 1)
            * (
                ((1 - gh["phi1"]) * ttemp1 * ur("delta_degC"))
                + ((1 - gh["phi2"]) * ttemp_2 * ur("delta_degC"))
            )
        )

        expected = (
            terf * ur(helper._erf_unit)
            - ((ttemp1 + ttemp_2) * ur(helper._temp1_unit)) * helper_twolayer.lambda0
            - efficacy_term
        )
        assert str(expected.units) == "watt / meter ** 2"

        res = helper._calculate_next_rndt(ttemp1, ttemp_2, terf, tefficacy)

        npt.assert_allclose(res, expected.magnitude)

        # check internal units make sense
        check_same_unit(self.tmodel._q1_unit, self.tmodel._q2_unit)
        check_same_unit(
            helper_twolayer._lambda0_unit, (1.0 * ur(self.tmodel._q2_unit) ** -1)
        )
        check_same_unit(
            self.tmodel._erf_unit,
            (
                (
                    1.0 * ur(self.tmodel._temp1_unit) / (1.0 * ur(self.tmodel._q1_unit))
                ).units
            ),
        )
        check_same_unit(
            self.tmodel._erf_unit, efficacy_term.units,
        )

    def test_step(self):
        # move to integration tests
        terf = np.array([3, 4, 5, 6, 7]) * ur("W/m^2")

        model = self.tmodel()
        model.set_drivers(terf)
        model.reset()

        model.step()
        assert model._timestep_idx == 0
        npt.assert_equal(model._temp1_mag[model._timestep_idx], 0)
        npt.assert_equal(model._temp2_mag[model._timestep_idx], 0)
        npt.assert_equal(model._rndt_mag[model._timestep_idx], 0)

        model.step()
        model.step()
        model.step()
        assert model._timestep_idx == 3

        npt.assert_equal(
            model._temp1_mag[model._timestep_idx],
            model._calculate_next_temp(
                model._delta_t_mag,
                model._temp1_mag[model._timestep_idx - 1],
                model._q1_mag,
                model._d1_mag,
                model._erf_mag[model._timestep_idx - 1],
            ),
        )

        npt.assert_equal(
            model._temp2_mag[model._timestep_idx],
            model._calculate_next_temp(
                model._delta_t_mag,
                model._temp2_mag[model._timestep_idx - 1],
                model._q2_mag,
                model._d2_mag,
                model._erf_mag[model._timestep_idx - 1],
            ),
        )

        npt.assert_equal(
            model._rndt_mag[model._timestep_idx],
            model._calculate_next_rndt(
                model._temp1_mag[model._timestep_idx - 1],
                model._temp2_mag[model._timestep_idx - 1],
                model._erf_mag[model._timestep_idx - 1],
                model._efficacy_mag,
            ),
        )

    def test_reset(self):
        terf = np.array([0, 1, 2]) * ur("W/m^2")

        model = self.tmodel()
        model.set_drivers(terf)

        def assert_is_nan_and_erf_shape(inp):
            assert np.isnan(inp).all()
            assert inp.shape == terf.shape

        model.reset()
        # after reset, we are not in any timestep
        assert np.isnan(model._timestep_idx)
        assert_is_nan_and_erf_shape(model._temp1_mag)
        assert_is_nan_and_erf_shape(model._temp2_mag)
        assert_is_nan_and_erf_shape(model._rndt_mag)

    def test_reset_run_reset(self):
        # move to integration tests
        terf = np.array([0, 1, 2, 3, 4, 5]) * ur("W/m^2")

        model = self.tmodel()
        model.set_drivers(terf)

        def assert_is_nan_and_erf_shape(inp):
            assert np.isnan(inp).all()
            assert inp.shape == terf.shape

        model.reset()
        assert_is_nan_and_erf_shape(model._temp1_mag)
        assert_is_nan_and_erf_shape(model._temp2_mag)
        assert_is_nan_and_erf_shape(model._rndt_mag)

        def assert_ge_zero_and_erf_shape(inp):
            assert not (inp < 0).any()
            assert inp.shape == terf.shape

        model.run()
        assert_ge_zero_and_erf_shape(model._temp1_mag)
        assert_ge_zero_and_erf_shape(model._temp2_mag)
        assert_ge_zero_and_erf_shape(model._rndt_mag)

        model.reset()
        assert_is_nan_and_erf_shape(model._temp1_mag)
        assert_is_nan_and_erf_shape(model._temp2_mag)
        assert_is_nan_and_erf_shape(model._rndt_mag)

    def test_get_two_layer_model_parameters(self, check_equal_pint):
        tq1 = 0.3 * ur("delta_degC/(W/m^2)")
        tq2 = 0.4 * ur("delta_degC/(W/m^2)")
        td1 = 3 * ur("yr")
        td2 = 300.0 * ur("yr")
        tefficacy = 1.2 * ur("dimensionless")

        start_paras = dict(d1=td1, d2=td2, q1=tq1, q2=tq2, efficacy=tefficacy,)

        mod_instance = self.tmodel(**start_paras)

        # for explanation of what is going on, see
        # impulse-response-equivalence.ipynb
        efficacy = tefficacy
        lambda0 = 1 / (tq1 + tq2)
        C = (td1 * td2) / (tq1 * td2 + tq2 * td1)

        a1 = lambda0 * tq1
        a2 = lambda0 * tq2
        tau1 = td1
        tau2 = td2

        C_D = (lambda0 * (tau1 * a1 + tau2 * a2) - C) / efficacy
        eta = C_D / (tau1 * a2 + tau2 * a1)

        expected = {
            "lambda0": lambda0,
            "du": C / (DENSITY_WATER * HEAT_CAPACITY_WATER),
            "dl": C_D / (DENSITY_WATER * HEAT_CAPACITY_WATER),
            "eta": eta,
            "efficacy": efficacy,
        }

        res = mod_instance.get_two_layer_parameters()

        assert res == expected

        # check circularity
        circular_params = TwoLayerModel(**res).get_impulse_response_parameters()
        for k, v in circular_params.items():
            check_equal_pint(v, start_paras[k])
