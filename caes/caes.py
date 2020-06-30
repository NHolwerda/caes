import pandas as pd
import CoolProp.CoolProp as CP  # http://www.coolprop.org/coolprop/HighLevelAPI.html#propssi-function
from math import log, pi
from pressure_drop import aquifer_dp, pipe_dp


# references
#
# Allen et al. 1983 -
#
# Battelle 2019 - Battelle, Delaware Geological Survey, Maryland Geological Survey, Pennsylvania Geological Survey,
# United States Geological Survey, Lamont-Doherty Earth Observatory at Columbia University, and Rutgers University.
# Mid-Atlantic U.S. Offshore Carbon Storage Resource Assessment Project Task 6 Risk Factor Analysis Report. DOE
# Cooperative Agreement No. DE-FE0026087. September 2019.
# https://edx.netl.doe.gov/dataset/mid-atlantic-final-technical-report
#
# Fukai et al. 2020 - Fukai, I., Keister, L., Ganesh, P.R., Cumming, L., Fortin, W., and Gupta, N., 2020, "Carbon
# dioxide storage resource assessment of Cretaceous- and Jurassic-age sandstones in the Atlantic offfshore region of the
# northeastern United States", Environmental Geosciences, V. 27, No. 1, 25-47.
# https://doi.org/10.1306/eg.09261919016
#


class CAES:

    def get_default_inputs():
        attributes = ['debug', 'steps', 'T_atm', 'p_atm', 'T_water', 'p_water', 'fuel_HHV', 'fuel_CO2',
                      'eta_mech', 'eta_gen',
                      'r_w', 'epsilon', 'depth',
                      'p_hydro_grad', 'p_frac_grad', 'safety_factor',
                      'T_grad_m', 'T_grad_b',
                      'r_f', 'thk', 'phi', 'Slr', 'k']
        inputs = pd.Series(index=attributes)

        inputs['debug'] = False  # debug
        inputs['steps'] = 100.0  # number of steps to use in single cycle simulation

        inputs['T_atm'] = 290.00  # 16.85 deg C [K], yearly average for Virginia coast
        inputs['p_atm'] = 101.325  # 1 atm [kPa]

        inputs['T_water'] = inputs['T_atm']  # same as atmospheric [K]
        inputs['p_water'] = inputs['p_atm']  # same as atmospheric [kPa]

        # methane, from https://www.engineeringtoolbox.com/co2-emission-fuels-d_1085.html, Accessed 5/12/20
        inputs['fuel_HHV'] = 15.4  # [kWh/kg fuel]
        inputs['fuel_CO2'] = 2.75  # [kg CO2/kg fuel]

        # mechanical and generator efficiencies
        inputs['eta_mech'] = 0.95  # [-]
        inputs['eta_gen'] = 0.975  # [-]

        # wellbore
        inputs['r_w'] = 0.53  # wellbore radius [m]
        inputs['epsilon'] = 0.002 * 1e-3  # pipe roughness [m]
        inputs['depth'] = 1402.35  # depth [m]

        # aquifer pressure gradient and limits
        inputs['p_hydro_grad'] = 10.0  # hydrostatic pressure gradient [MPa/km], Fukai et al. 2020
        inputs['p_frac_grad'] = 14.73  # fracture pressure gradient [MPa/km], Fukai et al. 2020
        inputs['safety_factor'] = 0.5  # operating pressure safety factor [-], Allen et al. 1983

        # aquifer thermal gradient
        inputs['T_grad_m'] = 0.007376668 * 3.28084  # m, slope [deg C/m], Battelle 2019
        inputs['T_grad_b'] = 7.412436  # b, intercept [deg C], Battelle 2019

        # storage geomechanical properties
        inputs['r_f'] = 500.0  # formation radius [m]
        inputs['h'] = 62.44  # thickness [m]
        inputs['phi'] = 0.2292  # porosity [-]
        inputs['Slr'] = 0.0  # liquid residual fraction [-]
        inputs['k'] = 38.67  # permeability [mD] #

        return inputs

    def __init__(self, inputs=get_default_inputs()):

        # debug option
        self.debug = inputs['debug']  # debug
        self.buffer = 1e-6  # to prevent warnings when limits are exceeded due to numerical rounding

        # number of timesteps to use in single cycle simulations
        self.steps = inputs['steps']  # (-)

        # constants
        self.g = 9.81  # gravitational constant [m/s^2]
        self.R = 8.314  # universal gas constant [kJ/kmol-K]

        # atmospheric air properties
        self.air = "Air.mix"  # CoolProp fluid name [-]
        self.M = 28.97  # molecular weight [kg/kmol]
        self.T_atm = inputs['T_atm']  # K
        self.p_atm = inputs['p_atm']  # [kPa]

        # water properties (used for cooling)
        self.water = 'Water'  # CoolProp fluid name [-]
        self.T_water = inputs['T_water']  # [K]
        self.p_water = inputs['p_water']  # [kPa]
        self.c_water = CP.PropsSI('CPMASS', 'T', self.T_water, 'P', self.p_water * 1000.0,
                                  self.water) / 1000.0  # constant pressure specific heat [kJ/kg-K]
        self.v_water = 1.0 / CP.PropsSI('D', 'T', self.T_water, 'P', self.p_water * 1000.0,
                                        self.water)  # specific volume (1/density) [m^3/kg]

        # fuel properties (default values are for natural gas)
        self.fuel_HHV = inputs['fuel_HHV']  # [kWh/kg]
        self.fuel_CO2 = inputs['fuel_CO2']  # [kg CO2/kg fuel]

        # efficiencies
        self.eta_mech = inputs['eta_mech']  # mechanical [fr]
        self.eta_gen = inputs['eta_gen']  # generator [fr]

        # wellbore
        self.r_w = inputs['r_w']  # wellbore radius [m]
        self.epsilon = inputs['epsilon']  # pipe roughness [m]
        self.depth = inputs['depth']  # depth [m]

        # aquifer pressure gradient and limits
        self.p_hydro_grad = inputs['p_hydro_grad']  # hydrostatic pressure gradient [MPa/km]
        self.p_frac_grad = inputs['p_frac_grad']  # fracture gradient [MPa/km]
        self.safety_factor = inputs['safety_factor']  # pressure safety factor [-]

        # calculated aquifer operating pressure range
        self.p_store_min = inputs['p_hydro_grad'] * inputs['depth']  # minimum storage pressure[kPa]
        self.p_store_range = inputs['safety_factor'] * (
                inputs['p_frac_grad'] - inputs['p_hydro_grad']) * inputs['depth']  # storage pressure range [kPa]
        self.p_store_max = self.p_store_min + self.p_store_range  # maximum storage pressure [kPa]

        # aquifer thermal gradient
        self.T_grad_m = inputs['T_grad_m']  # m, slope [deg C/m]
        self.T_grad_b = inputs['T_grad_b']  # b, intercept [deg C]

        # calculated aquifer temperature
        self.T_store_init = 273.15 + inputs['T_grad_m'] * inputs['depth'] + inputs[
            'T_grad_b']  # storage temperature [K]

        # storage geomechanical properties
        self.r_f = inputs['r_f']  # radius [m]
        self.h = inputs['h']  # thickness [m]
        self.phi = inputs['phi']  # porosity [-]
        self.Slr = inputs['Slr']  # residual liquid fraction [-]
        self.k = inputs['k']  # permeability [mD]

        # calculated storage volume and mass storage
        self.V_res = self.h * pi * self.r_f ** 2  # storage total volume [m^3]
        self.V = self.V_res * self.phi * (1.0 - self.Slr)  # volume available for air storage [m^3]
        self.m_store_min = self.p_store_min * self.V * self.M / (self.R * self.T_store_init)  # minimum [kg]
        self.m_store_max = self.p_store_max * self.V * self.M / (self.R * self.T_store_init)  # maximum [kg]

        # storage  - initialize state
        self.time = 0.0  # [hr]
        self.T_store = self.T_store_init  # storage temperature [K]
        self.p_store = self.p_store_min  # storage pressure [MPa]
        self.m_store = self.m_store_min  # mass stored [kg]

        # flow pressure drops
        self.dp_pipe = 0.0  # pipe friction and gravitational potential [kPa]
        self.dp_aquifer = 0.0  # aquifer pressure drop [kPa]

        # store error messages for current state
        self.error_msg = ''

        # dataframe to store data
        self.attributes_time_series = ['time', 'm_dot', 'delta_t', 'm_air',
                                       'pwr', 'energy_in', 'energy_out',
                                       'work_per_kg', 'total_work_per_kg', 'water_per_kg',
                                       'fuel_per_kg',
                                       'm_water', 'm_fuel',
                                       'p_store', 'T_store', 'm_store',
                                       'p0', 'p1', 'p2', 'p3',
                                       'error_msg']
        self.data = pd.DataFrame(columns=self.attributes_time_series)

    def update(self, m_dot=50.0, delta_t=1.0):
        """

        Updates the CAES system for the addition time step given a power request

        Designed to be kept the same for each caes architecture

        :param m_dot: mass flow rate, injection (+) or release (-) [kg/s]
        :param delta_t: time step [hr]
        :return:
        """

        # clear warning messages from previous time step
        self.error_msg = ''

        # create series to hold results from this time step
        s = pd.Series(data=0.0, index=self.attributes_time_series)
        s['m_dot'] = m_dot
        s['delta_t'] = delta_t
        s['m_air'] = m_dot * 3600 * delta_t  # mass injection/release [kg]

        # update time
        self.time = self.time + delta_t  # [hr]
        s['time'] = self.time

        # update flow pressure losses
        if abs(s['m_dot']) > 0:
            self.dp_pipe = self.calc_pipe_dp(m_dot)  # pipe friction and gravitational potential [kPa]
            self.dp_aquifer = self.calc_aquifer_dp(m_dot)  # aquifer pressure losses [kPa]

        # charge/discharge
        if s['m_air'] > 0.0:  # (charge)

            # pressure states
            s['p0'] = self.p_atm  # atmospheric pressure, compressor inlet
            s['p1'] = self.p_store + self.dp_aquifer + self.dp_pipe  # compressor outlet, pipe inlet
            s['p2'] = self.p_store + self.dp_aquifer  # pipe outlet
            s['p3'] = self.p_store  # storage pressure

            # calculate compressor performance
            s = self.charge_perf(s)

            # apply mechanical, generator and storage efficienies
            s['total_work_per_kg'] = s['work_per_kg'] / self.eta_mech / self.eta_gen

        elif s['m_air'] < 0.0:  # (discharge)

            # pressure states
            s['p3'] = self.p_store  # storage pressure
            s['p2'] = self.p_store - self.dp_aquifer  # pipe intlet
            s['p1'] = self.p_store - self.dp_aquifer - self.dp_pipe  # pipe outlet, expander inlet
            s['p0'] = self.p_atm  # atmospheric pressure, expander outlet

            # calculate expander performance
            s = self.discharge_perf(s)

            # apply mechanical, generator and storage efficienies
            s['total_work_per_kg'] = s['work_per_kg'] * self.eta_mech * self.eta_gen

        else:  # no flow
            # pressure states
            s['p0'] = self.p_atm
            s['p1'] = self.p_store
            s['p2'] = self.p_store
            s['p3'] = self.p_store

        # calculate the power per time step
        s['pwr'] = -1.0 * s['m_air'] * s['total_work_per_kg'] / (3600 * delta_t)  # 3600 converts from hr to s

        # calculate water and fuel use
        s['m_water'] = s['water_per_kg'] * abs(s['m_air'])
        s['m_fuel'] = s['fuel_per_kg'] * abs(s['m_air'])

        # calculate energy stored
        if s['m_air'] > 0.0:  # (charge)
            s['energy_in'] = -1.0 * s['m_air'] * s['total_work_per_kg'] / 3600  # [kWh]
        elif s['m_air'] < 0.0:  # (discharge)
            s['energy_out'] = -1.0 * s['m_air'] * s['total_work_per_kg'] / 3600  # [kWh]

        # update storage pressure
        s = self.update_storage_pressure(s)

        # -----------------------
        # finish storing results from current time step
        # -----------------------
        self.data = self.data.append(s, ignore_index=True)

    def single_cycle(self, m_dot=50):
        """
        runs a single cycle, charging and discharge in the number of steps specified in self.steps
        :param:
        m_dot [kg/s]
        :return:
        """

        # mass injection/release per timestep
        m_air = (self.m_store_max - self.m_store_min) / self.steps
        # timestep duration
        delta_t = m_air / (m_dot * 3600)  # [hr]

        if self.debug:
            print('mdot[kg/s]  : ' + str(round(m_dot, 2)))
            print('m_air[kg]   : ' + str(round(m_air, 2)))
            print('delta_t[hr] : ' + str(round(delta_t, 2)))

        # save initial state
        self.update(m_dot=0.0, delta_t=1e-6)

        if self.debug:
            print("Charging")

        for i in range(int(self.steps)):
            # charge
            self.update(m_dot=m_dot, delta_t=delta_t)
            if self.debug:
                print('/t' + str(i) + ' of ' + str(self.steps))

        if self.debug:
            print("Discharging")

        for i in range(int(self.steps)):
            # discharge
            self.update(m_dot=-1.0 * m_dot, delta_t=delta_t)
            if self.debug:
                print('/t' + str(i) + ' of ' + str(self.steps))

    def debug_perf(self, m_dot=50.0, delta_t=1.0):
        """
        runs several charge and discharge steps to debug calculations
        :param m_dot: mass flow rate [kg/s]
        :param delta_t: time step [hr]
        :return:
        """
        m_dot_in = 1.0 * m_dot
        m_dot_out = -1.0 * m_dot

        # charge
        self.update(m_dot=m_dot_in, delta_t=delta_t)
        self.update(m_dot=m_dot_in, delta_t=delta_t)
        self.update(m_dot=m_dot_in, delta_t=delta_t)
        self.update(m_dot=m_dot_in, delta_t=delta_t)
        self.update(m_dot=m_dot_in, delta_t=delta_t)
        # discharge
        self.update(m_dot=m_dot_out, delta_t=delta_t)
        self.update(m_dot=m_dot_out, delta_t=delta_t)
        self.update(m_dot=m_dot_out, delta_t=delta_t)
        self.update(m_dot=m_dot_out, delta_t=delta_t)
        self.update(m_dot=m_dot_out, delta_t=delta_t)

    def analyze_performance(self):
        """

        analyzes system performance - meant to be performed after completing a full cycle of charging/discharging

        designed to be kept the same for each caes architecutre

        :return: results - Pandas Series with the following entries
            RTE - roud trip efficiency [fr]
            fuel_per_MWh - fuel consumption oer MWh [kg]
            CO2_per_MWh - CO2 emissions per MWh [kg]
            water_per_MWh - water consumption per MWh [kg]
        """

        # compute performance
        energy_input_total = self.data.loc[:, 'energy_in'].sum()  # [kWh]
        energy_output_total = self.data.loc[:, 'energy_out'].sum()  # [kWh]
        water_input_total = self.data.loc[:, 'm_water'].sum()  # [kg]
        fuel_input_total = self.data.loc[:, 'm_fuel'].sum()  # [kg]
        CO2_fuel = fuel_input_total * self.fuel_CO2  # [ton]
        heat_input_total = fuel_input_total * self.fuel_HHV  # [kWh]
        RTE = energy_output_total / (energy_input_total + heat_input_total)

        # create series to hold results
        entries = ['RTE', 'kWh_in', 'kWh_out',
                   'kg_water_per_kWh', 'kg_CO2_per_kWh', 'kg_fuel_per_kWh', ]
        results = pd.Series(index=entries)
        results['RTE'] = RTE
        results['kWh_in'] = energy_input_total
        results['kWh_out'] = energy_output_total
        results['kg_water_per_kWh'] = water_input_total / energy_output_total
        results['kg_CO2_per_kWh'] = CO2_fuel / energy_output_total
        results['kg_fuel_per_kWh'] = fuel_input_total / energy_output_total

        return results

    def update_storage_pressure(self, s):
        """

        updates the pressure of the storage based on mass added/removed with machinery

        designed to be kept the same for each caes architecutre

        :param:
            s - pandas series containing performance of current time step and error messages
        :return:
            s - updated
        """
        # update storage mass and pressure
        self.m_store = self.m_store + s['m_air']
        self.p_store = self.m_store * self.R * self.T_store / (self.V * self.M)  # storage pressure

        # check storage pressure against limits
        if self.p_store < self.p_store_min - self.buffer:
            s['error_msg'] = 'Error: P_store < P_store_min (' + str(self.p_store) + ' < ' + str(self.p_store_min) + ')'
            print(s['error_msg'])
        elif self.p_store > self.p_store_max + self.buffer:
            s['error_msg'] = 'Error: P_store > P_store_max (' + str(self.p_store) + ' > ' + str(self.p_store_max) + ')'
            print(s['error_msg'])

        # store results
        s['p_store'] = self.p_store
        s['T_store'] = self.T_store
        s['m_store'] = self.m_store

        return s

    def charge_perf(self, s):
        """

        charge_perf - performance of compressors to store energy

        designed to be updated for each caes architecture

        :param:
            s - pandas series containing performance of current time step and error messages
        :return:
            s - updated including (at a minimum) the following entries:
                work_per_kg - compression work [kJ/kg air]
                water_per_kg - water use [kg water /kg air ]
                fuel_per_kg - fuel use [kg fuel /kg air]
        """

        # idealized isothermal process
        s['work_per_kg'] = self.R / self.M * self.T_atm * log(s['p0'] / s['p1'])  # [kJ/kg]
        s['water_per_kg'] = 0.0  # idealized process - no cooling water [kg/kg air]
        s['fuel_per_kg'] = 0.0  # isothermal - no heat input [kg/kg air]

        return s

    def discharge_perf(self, s):
        """
        discharge_perf - performance of expanders to release energy from storage

        designed to be updated for each caes architecture

        :param:
            s - pandas series containing performance of current time step and error messages
        :return:
            s - updated including (at a minimum) the following entries:
                work_per_kg - compression work [kJ/kg air]
                water_per_kg - water use [kg water /kg air ]
                fuel_per_kg - fuel use [kg fuel /kg air]
        """

        # idealized isothermal process
        s['work_per_kg'] = self.R / self.M * self.T_atm * log(s['p1'] / s['p0'])  # [kJ/kg]
        s['water_per_kg'] = 0.0  # idealized process - no cooling water [kg/kg air]
        s['fuel_per_kg'] = 0.0  # isothermal - no heat input [kg/kg air]

        return s

    def calc_aquifer_dp(self, m_dot):
        # fluid properties
        rho = CP.PropsSI('D', 'T', self.T_store, 'P', self.p_store * 1e3,
                         self.air)  # [kg/m3] inputs are degrees K and Pa
        mu = CP.PropsSI('V', 'T', self.T_store, 'P', self.p_store * 1e3,
                        self.air) * 1000  # Viscosity, convert Pa*s (output) to cP
        Z = CP.PropsSI('Z', 'T', self.T_store, 'P', self.p_store * 1e3, self.air)  # gas deviation factor [-]

        Q = m_dot / rho  # radial flow rate [m3/s]

        # aquifer pressure drop function
        dp = pipe_dp(Q=Q, r_f=self.r_f, r_w=self.r_w, k=self.k, mu=mu, h=self.h, p_f=self.p_store, T=self.T_store,
                     Z=Z)  # [MPa]
        dp = dp * 1e3  # [kPa]
        return dp

    def calc_pipe_dp(self, m_dot):

        if m_dot == 0:
            delta_p = 0.0
        elif m_dot > 0.0:  # injection
            delta_p = 0.0

        else:  # release
            delta_p = 0.0
        return delta_p
